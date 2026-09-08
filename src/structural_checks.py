"""Tier 1: the checks that need no rate table.

Eight of the eighteen error categories are properties of the invoice data
itself, or need at most the contract number and term. They cost nothing per
hospital once written, so they run across all five before any contract is
parsed and before any model is loaded.

Everything here operates on *invoice units* (see `data_loader.build_invoice_units`)
rather than on `invoice_id`, because `invoice_id` is not unique. Findings are
still reported against `invoice_id`, since that is the submission key.

Nothing in this module is probabilistic. A finding is an arithmetic or calendar
fact and is reported at confidence 1.0.
"""

import pandas as pd

COLUMNS = ["invoice_id", "category", "detail"]


def _f(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def check_line_total_arithmetic(line_items):
    """line_total_cents must equal quantity x unit_price_cents."""
    bad = line_items[line_items["line_total_cents"] != line_items["quantity"] * line_items["unit_price_cents"]]
    return _f([(r.invoice_id, "line_total_arithmetic",
                f"{r.line_id}: {r.quantity} x {r.unit_price_cents} = "
                f"{r.quantity * r.unit_price_cents}, billed {r.line_total_cents}")
               for r in bad.itertuples()])


def check_invoice_total_mismatch(units, line_items):
    """invoice_total_cents must equal the sum of that unit's line totals as billed."""
    sums = line_items.groupby("source_seq")["line_total_cents"].sum()
    u = units.assign(line_sum=units["source_seq"].map(sums))
    bad = u[u["line_sum"].notna() & (u["line_sum"] != u["invoice_total_cents"])]
    return _f([(r.invoice_id, "invoice_total_mismatch",
                f"{r.source_seq}: lines sum to {int(r.line_sum)}, invoice states {r.invoice_total_cents}")
               for r in bad.itertuples()])


def check_duplicate_invoice_id(units):
    """An invoice identifier may not be reused.

    We flag the *later* invoice of a reused pair, not both: the first use was
    legitimate. On hospital_1 the label's expected total always describes this
    later invoice, which is the evidence for that reading.
    """
    bad = units[units["reuses_id"]]
    return _f([(r.invoice_id, "duplicate_invoice_id",
                f"{r.source_seq} dated {r.invoice_date.date()} reuses an identifier already in use")
               for r in bad.itertuples()])


def check_malformed_service_date(line_items):
    """A service date that does not parse as a real calendar date."""
    bad = line_items[line_items["service_date"].isna()]
    return _f([(r.invoice_id, "malformed_service_date", f"{r.line_id}: {r.service_date_raw!r}")
               for r in bad.itertuples()])


def check_service_date_after_invoice_date(units, line_items, header):
    """A service may not be dated after the invoice that bills it.

    A date outside the contract term is also, necessarily, often after the
    invoice date. The hospital_1 labels do not double-label these: a service
    dated 2026-07-24 on an invoice dated 2024-06-02 is labelled
    `service_date_out_of_window` alone. We follow that precedence and only
    raise this category for dates that are inside the term.
    """
    start, end = pd.Timestamp(header["effective_from"]), pd.Timestamp(header["effective_to"])
    dates = units.set_index("source_seq")["invoice_date"]
    li = line_items.assign(invoice_date=line_items["source_seq"].map(dates))
    in_term = li["service_date"].between(start, end)
    bad = li[li["service_date"].notna() & li["invoice_date"].notna() & in_term
             & (li["service_date"] > li["invoice_date"])]
    return _f([(r.invoice_id, "service_date_after_invoice_date",
                f"{r.line_id}: service {r.service_date.date()} > invoice {r.invoice_date.date()}")
               for r in bad.itertuples()])


def check_service_date_out_of_window(line_items, header):
    """Every service date must fall inside the contract term."""
    start, end = pd.Timestamp(header["effective_from"]), pd.Timestamp(header["effective_to"])
    sd = line_items["service_date"]
    bad = line_items[sd.notna() & ((sd < start) | (sd > end))]
    return _f([(r.invoice_id, "service_date_out_of_window",
                f"{r.line_id}: {r.service_date.date()} outside {start.date()}..{end.date()}")
               for r in bad.itertuples()])


def check_contract_number_mismatch(units, header):
    """Each invoice must quote the contract number on the agreement."""
    expected = header["contract_number"]
    bad = units[units["contract_number"] != expected]
    return _f([(r.invoice_id, "contract_number_mismatch",
                f"quotes {r.contract_number!r}, expected {expected!r}")
               for r in bad.itertuples()])


def run_all(units, line_items, header):
    """Every tier-1 check, as one row per (invoice_id, category)."""
    out = pd.concat([
        check_line_total_arithmetic(line_items),
        check_invoice_total_mismatch(units, line_items),
        check_duplicate_invoice_id(units),
        check_malformed_service_date(line_items),
        check_service_date_after_invoice_date(units, line_items, header),
        check_service_date_out_of_window(line_items, header),
        check_contract_number_mismatch(units, header),
    ], ignore_index=True)
    return out.groupby(["invoice_id", "category"], as_index=False).agg(
        detail=("detail", "first"), n=("detail", "size"))
