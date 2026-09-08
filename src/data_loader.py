"""Loading and normalising the invoice data.

The CSV and JSONL files carry identical information; we read the CSVs because
the flat shape is what every downstream check wants.

Two rules govern this module:

1. Money stays an integer number of cents. We never let pandas infer a float
   for a monetary column, because a NaN would silently promote the column and
   a rounding error would then be indistinguishable from a billing error.
2. Dates are parsed *non-destructively*. `malformed_service_date` is one of the
   error categories we have to detect, so the raw string is preserved next to
   the parsed value and an unparseable date becomes NaT rather than an
   exception.

A third rule emerged from the data rather than the brief. `invoice_id` is *not*
a key: five hospital_1 identifiers are each carried by two genuinely different
invoices (different patient, date and total). The `line_id` prefix, however, is
unique — `INV-H1-000068` carries lines from both `L00068` and `L00155`, and the
two groups sum exactly to the two stated invoice totals. So the real invoice key
is the line_id prefix, and `build_invoice_units` reconstructs it. Everything
downstream prices a *unit*, not an `invoice_id`.
"""

import pandas as pd

from src.config import INVOICES, LABELS

MONEY_COLS = {"invoice_total_cents", "unit_price_cents", "line_total_cents"}


def _read_money(df, cols):
    """Coerce monetary columns to a nullable integer dtype, never to float."""
    for c in cols & set(df.columns):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def load_invoices(hospital):
    """One row per invoice, with `invoice_date` parsed alongside its raw string."""
    df = pd.read_csv(INVOICES / f"{hospital}_invoices.csv", dtype=str)
    df = _read_money(df, MONEY_COLS)
    for c in ["invoice_date", "admission_date", "discharge_date"]:
        df[f"{c}_raw"] = df[c]
        df[c] = pd.to_datetime(df[c], format="%Y-%m-%d", errors="coerce")
    return df


def load_line_items(hospital):
    """One row per line item, ordered as the contracts require them to be counted.

    Several contract rules (cumulative volume discounts, daily thresholds) are
    defined over line items "in Service Date order, and where two line items
    share a Service Date, in ascending order of line identifier". We sort here,
    once, so that every downstream pass inherits that order.
    """
    df = pd.read_csv(INVOICES / f"{hospital}_line_items.csv", dtype=str)
    df = _read_money(df, MONEY_COLS)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").astype("Int64")
    df["service_date_raw"] = df["service_date"]
    df["service_date"] = pd.to_datetime(df["service_date"], format="%Y-%m-%d", errors="coerce")
    # NaT dates sort last, which keeps the malformed rows out of the running
    # totals until we have decided what to do with them.
    return df.sort_values(["service_date", "line_id"], na_position="last").reset_index(drop=True)


def load_labels(hospital="hospital_1"):
    """Ground truth for the development hospital. Categories are `|`-separated."""
    df = pd.read_csv(LABELS / f"{hospital}_labels.csv", dtype=str)
    df["is_erroneous"] = df["is_erroneous"].astype(int)
    df["expected_total_cents"] = pd.to_numeric(df["expected_total_cents"]).astype("Int64")
    df["categories"] = df["error_categories"].fillna("").apply(
        lambda s: [c.strip() for c in s.split("|") if c.strip()]
    )
    return df


def load_hospital(hospital):
    """Convenience: invoices + line items for one hospital."""
    return load_invoices(hospital), load_line_items(hospital)


# --------------------------------------------------------------------------
# Reconstructing the true invoice key
# --------------------------------------------------------------------------

def build_invoice_units(invoices, line_items):
    """Attach the true invoice key (`source_seq`) to every invoice row.

    Where an `invoice_id` is reused, the rows are paired with their line-item
    groups in ascending order of both invoice date and line sequence. That
    pairing is not arbitrary: on hospital_1 it reproduces the stated invoice
    totals exactly for all five reused identifiers, and the label file's
    `expected_total_cents` always describes the *later* of the pair — the
    invoice that reused an identifier already in use. We therefore treat the
    earlier invoice as legitimate and flag the later one.

    Adds:
        source_seq       the true invoice key, e.g. "L00155"
        reuses_id        True for the offending (later) invoice of a reused id
    """
    li = line_items.copy()
    li["source_seq"] = li["line_id"].str.split("-").str[1]

    groups = (li.groupby(["invoice_id", "source_seq"])["line_total_cents"]
                .sum().reset_index().sort_values(["invoice_id", "source_seq"]))
    inv = invoices.sort_values(["invoice_id", "invoice_date"]).copy()

    inv["_rank"] = inv.groupby("invoice_id").cumcount()
    groups["_rank"] = groups.groupby("invoice_id").cumcount()
    merged = inv.merge(groups[["invoice_id", "source_seq", "_rank"]],
                       on=["invoice_id", "_rank"], how="left")

    merged["reuses_id"] = merged["_rank"] > 0
    return merged.drop(columns="_rank"), li
