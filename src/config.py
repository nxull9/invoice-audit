"""Project-wide paths and constants.

Every monetary amount in this project is an integer number of cents.
There are no floats anywhere in the financial path — see `audit_engine`.
"""

from pathlib import Path

# Resolve the repository root from this file, so the code runs identically
# from a local clone and from a Colab checkout.
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONTRACTS = DATA / "contracts"
INVOICES = DATA / "invoices"
LABELS = DATA / "labels"
REPORTS = ROOT / "reports"

HOSPITALS = ["hospital_1", "hospital_2", "hospital_3", "hospital_4", "hospital_5"]
DEV_HOSPITAL = "hospital_1"            # labelled; used for development only
SCORED_HOSPITALS = HOSPITALS[1:]       # hospitals 2-5 go in the submission

# The 18 error categories used by the hospital_1 label file. We reuse this
# vocabulary verbatim rather than inventing our own, so that per-category
# performance on the development set is directly reportable.
ERROR_CATEGORIES = [
    # --- detectable with no contract at all -------------------------------
    "line_total_arithmetic",
    "invoice_total_mismatch",
    "duplicate_invoice_id",
    "cross_invoice_duplicate",
    "service_date_after_invoice_date",
    "malformed_service_date",
    # --- need only the contract header ------------------------------------
    "service_date_out_of_window",
    "contract_number_mismatch",
    # --- need the rate table ----------------------------------------------
    "unit_price_mismatch",
    "wrong_unit_basis",
    "unknown_service",
    "daily_cap_exceeded",
    # --- need the contract rules ------------------------------------------
    "premium_incorrectly_applied",
    "premium_omitted",
    "volume_discount_incorrectly_applied",
    "volume_discount_omitted",
    "bundle_not_applied",
    "exclusion_window_violation",
]

# Unit bases as written in contracts -> as written on invoices.
UNIT_BASIS = {
    "per hour": "per_hour",
    "per day of service": "per_day",
    "per visit": "per_visit",
    "per procedure": "per_procedure",
    "per test": "per_test",
    "per item supplied": "per_item",
    "per night of occupancy": "per_night",
    "per unit dispensed": "per_unit_dispensed",
    "per hour, per item": "per_hour_per_item",   # compound basis; absent from hospital_1
}
