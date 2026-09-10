"""Run every tier for one hospital."""

import pandas as pd

from src.data_loader import load_invoices, load_line_items, build_invoice_units
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


def audit(data_root, hospital, spec=None):
    """Run every tier for one hospital and return the pieces the report needs.

    `spec` may be supplied directly, which is how hospital 2 is audited: its contract
    is prose, so its spec comes from a model rather than from a table reader.
    """
    header = read_header(data_root, hospital)
    if spec is None:
        spec = compile_contract(data_root, hospital)
    invoices = load_invoices(data_root, hospital)
    line_items = load_line_items(data_root, hospital)
    units = build_invoice_units(invoices, line_items)

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
