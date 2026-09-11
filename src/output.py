"""Turn an audit into what a person or the grader reads: an explanation, a confidence,
and submission.csv.

Confidence is composed from evidence, not asserted. Three things weaken it: a finding
whose category is a judgement rather than an arithmetic fact; a service the resolver
was unsure about; and a contract that was read by a model rather than by regex.
Arithmetic facts are exempt from the last two, because they hold whoever read the
contract and however the description was resolved.
"""

import pandas as pd


# How strong the evidence behind each category is. Arithmetic and calendar facts are
# certain. Rule-based categories depend on a contract reading and a resolved service.
# daily_cap_exceeded is lowest: the expected total for it cannot be recovered (decision
# log item 4), only the flag.
CATEGORY_STRENGTH = {
    "line_total_arithmetic": 1.00, "invoice_total_mismatch": 1.00,
    "duplicate_invoice_id": 1.00, "malformed_service_date": 1.00,
    "service_date_after_invoice_date": 1.00, "service_date_out_of_window": 1.00,
    "contract_number_mismatch": 1.00,
    "unknown_service": 0.90, "wrong_unit_basis": 0.92, "unit_price_mismatch": 0.88,
    "cross_invoice_duplicate": 0.90, "exclusion_window_violation": 0.85,
    "bundle_not_applied": 0.88, "premium_omitted": 0.85,
    "premium_incorrectly_applied": 0.85, "volume_discount_omitted": 0.85,
    "volume_discount_incorrectly_applied": 0.85, "daily_cap_exceeded": 0.75,
    "wrong_facility_multiplier": 0.88, "wrong_tier_multiplier": 0.88,
}
ARITHMETIC = {c for c, s in CATEGORY_STRENGTH.items() if s == 1.0}
CLEAN_BASE = 0.95          # a clean invoice is never certain: an error type we do not
                           # model would pass unnoticed
UNKNOWN_CATEGORY = 0.70


def extraction_confidence(spec):
    """1.0 for a regex-read contract, less for a model-read one."""
    return float(spec["provenance"].get("confidence", 1.0))


def resolution_confidence(result, source_seq):
    """The weakest service resolution among an invoice's line items."""
    lines = result["priced"][result["priced"]["source_seq"] == source_seq]
    conf = dict(zip(result["resolution"]["description"], result["resolution"]["confidence"]))
    values = [conf.get(d, 0.0) for d in lines["description"]]
    return min(values) if values else 0.0


def invoice_confidence(categories, extraction_conf, resolution_conf):
    """Compose one number from the three kinds of evidence."""
    if categories:
        base = min(CATEGORY_STRENGTH.get(c, UNKNOWN_CATEGORY) for c in categories)
        if all(c in ARITHMETIC for c in categories):
            return round(base, 3)
        return round(base * extraction_conf * resolution_conf, 3)
    return round(CLEAN_BASE * extraction_conf * resolution_conf, 3)


def collapse_reused_ids(totals):
    """One row per invoice_id, the submission key.

    Where an identifier is reused, the later invoice unit is the one the labels
    describe (decision log item 1), so it is the one reported.
    """
    return (totals.sort_values("source_seq")
                  .groupby("invoice_id", as_index=False).last())


def submission_rows(result):
    """The submission rows for one audited hospital."""
    spec_conf = extraction_confidence(result["spec"])
    by_invoice = result["findings"].groupby("invoice_id")["category"].apply(list).to_dict()
    rows = []
    for r in collapse_reused_ids(result["totals"]).itertuples():
        cats = sorted(by_invoice.get(r.invoice_id, []))
        rows.append({
            "invoice_id": r.invoice_id,
            "flagged": int(bool(cats)),
            "error_category": "|".join(cats),
            "expected_total_cents": int(r.expected_total_cents),
            "billed_total_cents": int(r.invoice_total_cents),
            "confidence": invoice_confidence(
                cats, spec_conf, resolution_confidence(result, r.source_seq)),
        })
    return pd.DataFrame(rows, columns=SUBMISSION_COLUMNS)


SUBMISSION_COLUMNS = ["invoice_id", "flagged", "error_category",
                      "expected_total_cents", "billed_total_cents", "confidence"]


def validate_submission(submission, expected_ids=None):
    """Every reason a submission could be rejected. Returns a list of problems; empty is good."""
    problems = []
    if list(submission.columns) != SUBMISSION_COLUMNS:
        problems.append(f"columns are {list(submission.columns)}, expected {SUBMISSION_COLUMNS}")
        return problems
    if not submission["invoice_id"].is_unique:
        problems.append("duplicate invoice_id rows")
    if not submission["flagged"].isin([0, 1]).all():
        problems.append("flagged must be 0 or 1")
    if not submission["confidence"].between(0, 1).all():
        problems.append("confidence outside [0, 1]")
    for col in ("expected_total_cents", "billed_total_cents"):
        if not pd.api.types.is_integer_dtype(submission[col]):
            problems.append(f"{col} is not integer")
    flagged = submission["flagged"] == 1
    if (submission.loc[flagged, "error_category"].fillna("") == "").any():
        problems.append("a flagged invoice has no error_category")
    if (submission.loc[~flagged, "error_category"].fillna("") != "").any():
        problems.append("an unflagged invoice carries an error_category")
    if expected_ids is not None:
        missing = set(expected_ids) - set(submission["invoice_id"])
        extra = set(submission["invoice_id"]) - set(expected_ids)
        if missing:
            problems.append(f"{len(missing)} invoices missing, e.g. {sorted(missing)[:3]}")
        if extra:
            problems.append(f"{len(extra)} unexpected invoices, e.g. {sorted(extra)[:3]}")
    return problems


def write_submission(results, path, expected_ids=None):
    """Combine per-hospital results, validate, write. Raises if invalid."""
    submission = pd.concat([submission_rows(r) for r in results], ignore_index=True)
    problems = validate_submission(submission, expected_ids)
    if problems:
        raise ValueError("submission invalid:\n  " + "\n  ".join(problems))
    submission.to_csv(path, index=False)
    return submission


# --------------------------------------------------------------------------
# Explaining one invoice
# --------------------------------------------------------------------------

def contract_source(spec):
    """One phrase saying how this contract was read, for the explanation."""
    prov = spec["provenance"]
    if "model" in prov:
        how = "replayed from runs/" if prov.get("replayed") else "called live"
        return f"a model ({prov['model']}, prompt {prov['prompt_version']}, {how})"
    return f"tables by regex ({prov.get('services', 'rate schedule')})"


def explain_invoice(result, invoice_id):
    """Everything a reviewer needs to see about one invoice, as a dict.

    Returns None if the invoice is not in this hospital's data.
    """
    units = result["units"][result["units"]["invoice_id"] == invoice_id]
    if units.empty:
        return None
    unit = units.sort_values("source_seq").iloc[-1]        # the later unit if reused
    seq = unit["source_seq"]
    findings = result["findings"][result["findings"]["invoice_id"] == invoice_id]
    total = result["totals"][result["totals"]["source_seq"] == seq].iloc[0]
    lines = result["priced"][result["priced"]["source_seq"] == seq]
    cats = sorted(findings["category"])

    evidence = [f"{r.category}: {r.detail}" for r in findings.itertuples()]
    line_rows = []
    for r in lines.itertuples():
        line_rows.append({
            "line_id": r.line_id, "service_date": str(r.service_date.date()) if pd.notna(r.service_date) else r.service_date_raw,
            "description": r.description, "service": r.service if isinstance(r.service, str) else "(unresolved)",
            "qty": int(r.quantity), "billed_rate": int(r.unit_price_cents),
            "expected_rate": None if pd.isna(r.expected_unit_rate) else int(r.expected_unit_rate),
            "billed_total": int(r.line_total_cents),
            "expected_total": None if pd.isna(r.expected_line_total) else int(r.expected_line_total),
            "adjustments": r.adjustments or "",
        })

    return {
        "hospital": result["hospital"],
        "invoice_id": invoice_id,
        "reused_id": bool(len(units) > 1),
        "contract_number": unit["contract_number"],
        "invoice_date": str(unit["invoice_date"].date()) if pd.notna(unit["invoice_date"]) else unit["invoice_date_raw"],
        "patient_id": unit["patient_id"],
        "billed_total_cents": int(total["invoice_total_cents"]),
        "expected_total_cents": int(total["expected_total_cents"]),
        "flagged": bool(cats),
        "categories": cats,
        "confidence": invoice_confidence(cats, extraction_confidence(result["spec"]),
                                         resolution_confidence(result, seq)),
        "contract_source": contract_source(result["spec"]),
        "evidence": evidence,
        "lines": line_rows,
    }
