"""Classify a mispriced line by which adjustment was mishandled.

The engine records the rate each alternative reading would produce, so the billed
rate identifies the specific error rather than a generic price mismatch.
`unit_price_mismatch` means the billed rate is not one the contract can produce.
"""

import pandas as pd

from src.contract_spec import bundle_partner

# Categories that flag a breach without changing what is owed. Established from
# the single-category invoices on hospital 1, every one of which has
# expected_total_cents exactly equal to the billed total.
COMPLIANCE_ONLY = {
    "wrong_unit_basis", "unknown_service", "malformed_service_date",
    "service_date_after_invoice_date", "service_date_out_of_window",
    "contract_number_mismatch", "duplicate_invoice_id",
}


def classify_line(row, spec):
    """Every category this line item breaches. May be empty, may be several."""
    found = []
    svc = spec["services"].get(row.service) if row.service else None
    if svc is None:
        return found

    if row.unit_basis_as_billed != svc["unit_basis"]:
        found.append("wrong_unit_basis")

    if row.disallowed:
        found.append(row.disallowed)

    if pd.notna(row.billable_quantity) and row.billable_quantity < row.quantity:
        found.append("daily_cap_exceeded")

    if pd.isna(row.expected_unit_rate) or row.expected_unit_rate == row.unit_price_cents:
        return found

    billed, expected, alt = int(row.unit_price_cents), int(row.expected_unit_rate), row.alternatives
    used = row.adjustments or ""

    # Which alternative reading did the hospital actually bill?
    if "bundle" in used and billed == alt.get("standalone"):
        found.append("bundle_not_applied")
    elif "volume" in used and billed == alt.get("no_discount"):
        found.append("volume_discount_omitted")
    elif "volume" not in used and billed == alt.get("with_discount"):
        found.append("volume_discount_incorrectly_applied")
    elif ("threshold" in used or "business-day" in used) and billed == alt.get("no_premium"):
        found.append("premium_omitted")
    elif ("threshold" not in used and "business-day" not in used
          and billed in {alt.get("with_threshold"), alt.get("with_nbd")}):
        found.append("premium_incorrectly_applied")
    else:
        found.extend(_wrong_grid_cell(billed, alt) or ["unit_price_mismatch"])
    return found


def _wrong_grid_cell(billed, alt):
    """Did the provider price the right service against the wrong grid column?

    Hospitals with a facility x plan-tier grid (hospital 5) admit an error that
    hospital 1 cannot express: the correct service, correctly adjusted, but read
    off the wrong column. The engine prices the line under every column, so we
    can name which one was used instead of falling back on a generic mismatch.

    These two categories extend the hospital_1 label vocabulary. That vocabulary
    has no word for them because hospital 1 has no multipliers, and the
    submission format allows a free-text category. Reporting them as
    `unit_price_mismatch` would be true but less useful to a reviewer, who would
    have to rediscover the pattern by hand.
    """
    grid, cell = alt.get("grid"), alt.get("grid_cell")
    if not grid or not cell:
        return []
    right_f, right_t = cell
    for (fk, tk), value in grid.items():
        if value != billed or (fk, tk) == cell:
            continue
        out = []
        if fk != right_f:
            out.append("wrong_facility_multiplier")
        if tk != right_t:
            out.append("wrong_tier_multiplier")
        return out
    return []


def classify(priced, spec):
    """Line-level findings for a whole hospital, as (invoice_id, category, detail)."""
    rows = []
    for r in priced.itertuples():
        for cat in classify_line(r, spec):
            rows.append({
                "invoice_id": r.invoice_id, "category": cat,
                "detail": (f"{r.line_id} {r.service}: billed {r.unit_price_cents} x {r.quantity}"
                           f" = {r.line_total_cents}, expected "
                           f"{r.expected_unit_rate} x {r.billable_quantity}"
                           f" = {r.expected_line_total}"
                           + (f" [{r.adjustments}]" if r.adjustments else "")),
            })
    return pd.DataFrame(rows, columns=["invoice_id", "category", "detail"])


def expected_totals(priced, units):
    """Expected invoice total = the sum of the repriced line totals.

    Where a line could not be priced at all (an unknown service), the billed
    amount stands: we have no contractual basis to reprice it, and saying so is
    better than inventing a number.
    """
    p = priced.copy()
    p["contribution"] = p["expected_line_total"].fillna(p["line_total_cents"])
    totals = p.groupby("source_seq")["contribution"].sum()
    out = units[["invoice_id", "source_seq", "invoice_total_cents"]].copy()
    out["expected_total_cents"] = out["source_seq"].map(totals).astype("Int64")
    return out
