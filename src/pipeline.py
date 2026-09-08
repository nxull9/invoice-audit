"""End to end: contract + invoices -> findings, expected totals, confidence.

Three tiers of evidence, in increasing order of what they cost and decreasing
order of how certain they are:

  1. structural   arithmetic and calendar facts; no contract needed
  2. resolution   which contracted service a billing description refers to
  3. repricing    what the contract says the line should have cost

A finding from tier 1 is a fact. A finding from tier 3 is only as good as the
contract extraction and the service resolution beneath it, so its confidence is
bounded by theirs — that propagation is what `confidence.py` does.
"""

import pandas as pd

from src.data_loader import load_hospital, build_invoice_units
from src.contract_header import read_header
from src.compile_contract import compile_contract
from src.resolver import resolve
from src.audit_engine import reprice
from src.error_classifier import classify, expected_totals
from src import structural_checks as sc


def unknown_service_findings(resolution, line_items):
    """Invoices carrying a description that resolves to no contracted service."""
    unknown = set(resolution.loc[resolution["method"] == "unknown_service", "description"])
    hit = line_items[line_items["description"].isin(unknown)]
    return pd.DataFrame([
        {"invoice_id": r.invoice_id, "category": "unknown_service",
         "detail": f"{r.line_id}: {r.description!r} matches no contracted service"}
        for r in hit.itertuples()
    ], columns=["invoice_id", "category", "detail"])


def audit(hospital):
    """Run every tier for one hospital and return the pieces the report needs."""
    header = read_header(hospital)
    spec = compile_contract(hospital)
    invoices, line_items = load_hospital(hospital)
    units, line_items = build_invoice_units(invoices, line_items)

    resolution = resolve(spec, line_items)
    priced = reprice(spec, units, line_items, resolution)

    findings = pd.concat([
        sc.run_all(units, line_items, header),
        unknown_service_findings(resolution, line_items),
        classify(priced, spec),
    ], ignore_index=True)

    findings = findings.groupby(["invoice_id", "category"], as_index=False).agg(
        detail=("detail", "first"), n_lines=("detail", "size"))

    return {"hospital": hospital, "spec": spec, "units": units, "line_items": line_items,
            "resolution": resolution, "priced": priced, "findings": findings,
            "totals": expected_totals(priced, units)}
