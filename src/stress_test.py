"""Generalisation tests for the audit pipeline.

Hospital 1 reaches precision and recall of 1.000, which is the only score the project
can measure and therefore the one least worth trusting. Four decisions were calibrated
on those labels, and the categories carry three to twelve examples each.

These tests answer a different question: does the system catch errors it has never
been shown? Faults are injected into invoices the labels mark as clean, so every
detection is of an error absent from the calibration set, and every flag raised on an
untouched invoice is a false positive.
"""

import copy
import random

import pandas as pd

from src.contract_spec import rate_on
from src.money import uplift, discount


def _clean_invoices(labels):
    return list(labels.loc[labels["is_erroneous"] == 0, "invoice_id"])


def inject(units, line_items, spec, labels, n_per_kind=12, seed=0):
    """Return (units, line_items, truth) with synthetic faults in clean invoices.

    `truth` maps invoice_id -> the category injected, so recall is measured against
    faults this system has never seen rather than against the labels it was tuned on.
    """
    rng = random.Random(seed)
    units, line_items = units.copy(), line_items.copy()
    seq_of = dict(zip(units.invoice_id, units.source_seq))
    pool = [i for i in _clean_invoices(labels) if i in seq_of]
    rng.shuffle(pool)

    truth, used = {}, set()

    def take(predicate=None):
        for invoice_id in pool:
            if invoice_id in used:
                continue
            rows = line_items.index[line_items.source_seq == seq_of[invoice_id]]
            if not len(rows):
                continue
            if predicate is None:
                used.add(invoice_id)
                return invoice_id, list(rows)
            keep = [r for r in rows if predicate(line_items.loc[r])]
            if keep:
                used.add(invoice_id)
                return invoice_id, keep
        return None, None

    def record(invoice_id, category):
        truth[invoice_id] = category

    # --- arithmetic and calendar faults ----------------------------------
    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        line_items.loc[rows[0], "line_total_cents"] += 137
        record(iid, "line_total_arithmetic")

    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        mask = units.source_seq == seq_of[iid]
        units.loc[mask, "invoice_total_cents"] = units.loc[mask, "invoice_total_cents"] + 500
        record(iid, "invoice_total_mismatch")

    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        line_items.loc[rows[0], "service_date"] = pd.NaT
        line_items.loc[rows[0], "service_date_raw"] = "2025-02-30"
        record(iid, "malformed_service_date")

    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        line_items.loc[rows[0], "service_date"] = pd.Timestamp("2023-05-04")
        record(iid, "service_date_out_of_window")

    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        units.loc[units.source_seq == seq_of[iid], "contract_number"] = "INS-XX-0000-0000"
        record(iid, "contract_number_mismatch")

    # --- rate faults, which need the contract ----------------------------
    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        row = rows[0]
        price = int(line_items.loc[row, "unit_price_cents"])
        line_items.loc[row, "unit_price_cents"] = price + 1000
        line_items.loc[row, "line_total_cents"] = (price + 1000) * int(line_items.loc[row, "quantity"])
        record(iid, "unit_price_mismatch")

    other_basis = {"per_hour": "per_visit", "per_visit": "per_hour", "per_day": "per_night",
                   "per_night": "per_day", "per_item": "per_test", "per_test": "per_item",
                   "per_procedure": "per_visit", "per_unit_dispensed": "per_item",
                   "per_hour_per_item": "per_hour"}
    for _ in range(n_per_kind):
        iid, rows = take()
        if not iid:
            break
        row = rows[0]
        billed = line_items.loc[row, "unit_basis_as_billed"]
        line_items.loc[row, "unit_basis_as_billed"] = other_basis.get(billed, "per_visit")
        record(iid, "wrong_unit_basis")

    capped = {n for n, s in spec["services"].items() if s["daily_cap"]}
    for _ in range(n_per_kind):
        iid, rows = take(lambda r: r.get("service") in capped)
        if not iid:
            break
        row = rows[0]
        cap = spec["services"][line_items.loc[row, "service"]]["daily_cap"]
        qty = cap + 5
        price = int(line_items.loc[row, "unit_price_cents"])
        line_items.loc[row, "quantity"] = qty
        line_items.loc[row, "line_total_cents"] = price * qty
        record(iid, "daily_cap_exceeded")

    return units, line_items, truth


def score(findings, truth, labels):
    """Recall on injected faults, and false positives on untouched clean invoices.

    The control group is invoices the labels mark clean *and* which received no
    injection. Including the genuinely erroneous ones would count correct detections
    as false positives.
    """
    flagged = set(findings["invoice_id"])
    injected = set(truth)
    untouched = set(_clean_invoices(labels)) - injected

    rows = []
    for category in sorted(set(truth.values())):
        wanted = {i for i, c in truth.items() if c == category}
        caught = wanted & flagged
        named = {i for i in caught
                 if category in set(findings.loc[findings.invoice_id == i, "category"])}
        rows.append({"injected_category": category, "n": len(wanted),
                     "detected": len(caught), "detection_recall": round(len(caught) / len(wanted), 3),
                     "named_correctly": len(named),
                     "naming_recall": round(len(named) / len(wanted), 3)})
    summary = pd.DataFrame(rows)
    false_positive = len(flagged & untouched)
    return summary, {"injected": len(injected), "detected": len(injected & flagged),
                     "untouched": len(untouched), "false_positives": false_positive,
                     "false_positive_rate": round(false_positive / max(1, len(untouched)), 4)}
