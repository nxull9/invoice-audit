"""Project-wide paths and constants.

Every monetary amount in this project is an integer number of cents.
There are no floats anywhere in the financial path — see `pricing`.
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
PROMPTS = ROOT / "prompts"
RUNS = ROOT / "runs"                   # recorded model replies; replayed so no key is needed

HOSPITALS = ["hospital_1", "hospital_2", "hospital_3", "hospital_4", "hospital_5"]
DEV_HOSPITAL = "hospital_1"            # labelled; used for development only
SCORED_HOSPITALS = HOSPITALS[1:]       # hospitals 2-5 go in the submission

# Hospital 2 states its rules as prose and is read by a model. The others are tables
# and are read by regex. Which model and which prompt version are pinned here so a
# run is reproducible from its recording in RUNS.
#
# prose_v2, gpt-4o. Under prose_v1, checked rule by rule against the contract text
# (evaluation/verify_hospital_2.py), gpt-4o filed three threshold premiums as daily
# caps (7 defects) and deepseek invented two caps (2). prose_v2 adds one section
# separating the three look-alike sentence shapes; both models then read all 76
# clauses with 0 defects. With both clean, the original rule applies: the faster one.
# Decision log item 11.
EXTRACTION_MODEL = "gpt-4o"
PROSE_PROMPT_VERSION = "prose_v2"
# A model-read contract is trusted less than a regex-read one. The verifier shows the
# rules were read correctly for THIS contract; it says nothing about the next one, and
# there are no labels behind it, so the penalty stays. Applied to confidence -- output.py.
MODEL_EXTRACTION_CONFIDENCE = 0.85

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
