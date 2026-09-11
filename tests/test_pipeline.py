"""Regression tests.

Every failure below was shipped at least once. They exist so that the paths which are
awkward to reach by hand -- replaying a recording, tolerating a model's output shape --
are exercised before a change reaches a live session.

Run with:  python -m pytest tests -q     (or: python tests/test_pipeline.py)
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src import (audit, checks, classify, compile_contract, contracts, data, evaluation,
                 extract, llm, pricing, resolver)
from evaluation import chunking, spec_diff, stress_test

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DEV = "hospital_1"


# --------------------------------------------------------------------------
# model reply handling
# --------------------------------------------------------------------------

def test_parse_json_accepts_every_shape_a_model_returns():
    cases = {
        "plain": '{"services": []}',
        "fenced": '```json\n{"services": []}\n```',
        "chatty": 'Sure! Here it is:\n{"services": []}\nHope that helps.',
        "wrapped_record": {"reply": '{"services": []}', "usage": {"input_tokens": 5}},
        "already_decoded": {"services": []},
    }
    for label, value in cases.items():
        payload, err = llm.parse_json(value)
        assert err is None, f"{label}: {err}"
    assert llm.parse_json("not json at all")[0] is None
    assert llm.parse_json(12345)[1] is not None


def test_normalise_payload_handles_missing_envelope():
    assert extract.normalise_payload({"services": [1]}) == ([1], None)
    assert extract.normalise_payload([1, 2])[1] == "bare_list"
    assert extract.normalise_payload({"service": "A"})[1] == "single_object"
    assert extract.normalise_payload({"nope": 1})[0] == []


def test_replay_reports_recorded_usage_and_flags_recordings_without_it():
    with_usage = llm.ReplayModel(
        {"0": {"reply": '{"services": []}',
               "usage": {"input_tokens": 848, "output_tokens": 1211, "seconds": 16.0}}})
    _, usage = with_usage.generate("s", "u")
    assert usage["input_tokens"] == 848 and usage["telemetry"] == "recorded"

    without = llm.ReplayModel({"0": '{"services": []}'})
    _, usage = without.generate("s", "u")
    assert usage["input_tokens"] == 0 and usage["telemetry"] == "missing"


# --------------------------------------------------------------------------
# extraction validation
# --------------------------------------------------------------------------

def _chunk():
    text = open(f"{DATA}/contracts/hospital_5/network_reimbursement_agreement.md").read()
    return chunking.table_chunks(text, ["Table 1"])[0]


def test_validation_gates_on_substance_not_formatting():
    chunk = _chunk()
    row = [l for l in chunk["text"].splitlines() if l.strip().startswith("|")][2]
    base = {"service": "Advanced Cardiac Ventilation Support", "unit_basis": "per_hour",
            "rates": [{"rate_cents": 3375}], "daily_cap": 24, "confidence": 0.95}

    for quote in (row.strip(), "Advanced Cardiac Ventilation Support  per hour", ""):
        rec, problems = extract.validate_service({**base, "source_quote": quote}, chunk["text"])
        assert rec is not None, problems

    invented = {**base, "service": "Invented Cardiac Nonsense", "source_quote": row.strip()}
    assert extract.validate_service(invented, chunk["text"])[0] is None

    for bad in ({"unit_basis": "per week"}, {"rates": []}, {"rates": [{"rate_cents": 0}]}):
        assert extract.validate_service({**base, **bad}, chunk["text"])[0] is None


def test_validation_reads_both_prompt_schemas():
    chunk = _chunk()
    row = [l for l in chunk["text"].splitlines() if l.strip().startswith("|")][2]
    v1 = {"service": "Advanced Cardiac Ventilation Support", "unit_basis": "per_hour",
          "rate_cents": 3375, "source_quote": row.strip()}
    v2 = {**{k: v for k, v in v1.items() if k != "rate_cents"},
          "rates": [{"rate_cents": 3375, "valid_from": None, "valid_to": "2024-12-31"},
                    {"rate_cents": 4000, "valid_from": "2025-01-01", "valid_to": None}]}
    assert len(extract.validate_service(v1, chunk["text"])[0]["rates"]) == 1
    assert len(extract.validate_service(v2, chunk["text"])[0]["rates"]) == 2


def test_extract_contract_survives_a_broken_reply():
    chunks = chunking.table_chunks(
        open(f"{DATA}/contracts/hospital_5/network_reimbursement_agreement.md").read(),
        ["Table 1"])[:2]
    model = llm.ReplayModel({"0": '{"services": []}', "1": "I cannot read this."})
    spec, frame, tel = extract.extract_contract(
        model, "prompt", chunks, contracts.read_header(DATA, "hospital_5"),
        "hospital_5", verbose=False)
    assert tel.parse_error.notna().sum() == 1
    assert len(spec["warnings"]) >= 1


# --------------------------------------------------------------------------
# contracts and engine
# --------------------------------------------------------------------------

def test_every_tabular_contract_compiles_without_warnings():
    for h in ["hospital_1", "hospital_3", "hospital_4", "hospital_5"]:
        spec = compile_contract.compile_contract(DATA, h)
        assert not spec["warnings"], (h, spec["warnings"])
        assert spec["services"]


def test_amendment_gives_seven_services_two_dated_rates():
    spec = compile_contract.compile_contract(DATA, "hospital_3")
    multi = [s for s in spec["services"].values() if len(s["rates"]) > 1]
    assert len(multi) == 7
    assert sum(len(s["rates"]) for s in spec["services"].values()) == 127


def test_scorer_finds_exactly_the_faults_injected_into_a_spec():
    gold = compile_contract.compile_contract(DATA, "hospital_5")
    assert spec_diff.compare_specs(gold, gold)["rate_exact"] == 1.0
    bad = copy.deepcopy(gold)
    names = sorted(bad["services"])
    del bad["services"][names[0]]
    bad["services"]["Invented"] = contracts.new_service(
        "Invented", "per_visit", [contracts.new_rate(1)])
    bad["services"][names[5]]["rates"][0]["cents"] += 5
    m = spec_diff.compare_specs(gold, bad)
    assert m["missed_services"] == 1 and m["hallucinated_services"] == 1
    assert m["rate_exact"] < 1.0


def test_hospital_one_scores_perfectly_and_reproduces_expected_totals():
    result = audit.audit_hospital(DATA, DEV)
    labels = data.load_labels(DATA)
    scores = evaluation.detection_scores(result["findings"].invoice_id.unique(), labels)
    assert scores["precision"] == 1.0 and scores["recall"] == 1.0

    totals = (result["totals"].sort_values("source_seq")
              .groupby("invoice_id", as_index=False).last()
              .merge(labels[["invoice_id", "expected_total_cents"]], on="invoice_id",
                     suffixes=("_pred", "_true")))
    exact = (totals.expected_total_cents_pred == totals.expected_total_cents_true).sum()
    assert exact == 909, exact


def test_injected_faults_are_caught_without_false_positives():
    labels = data.load_labels(DATA)
    spec = compile_contract.compile_contract(DATA, DEV)
    header = contracts.read_header(DATA, DEV)
    li = data.load_line_items(DATA, DEV)
    units = data.build_invoice_units(data.load_invoices(DATA, DEV), li)
    res = resolver.resolve(spec, li)
    li = li.assign(service=li.description.map(dict(zip(res.description, res.service))))

    u2, li2, truth = stress_test.inject(units, li, spec, labels, n_per_kind=12, seed=0)
    res2 = resolver.resolve(spec, li2)
    priced = pricing.reprice(spec, u2, li2, res2)
    findings = pd.concat([checks.run_all(u2, li2, header),
                          audit.unknown_service_findings(res2, li2),
                          classify.classify(priced, spec)], ignore_index=True)
    _, summary = stress_test.score(findings, truth, labels)
    assert summary["detected"] == summary["injected"]
    assert summary["false_positives"] == 0


def test_money_rounds_after_each_step():
    from decimal import Decimal
    from src import money
    assert money.discount(112825, Decimal("0.10")) == 101543
    assert money.apply(19775, Decimal("0.95")) == 18786


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{failures} failing")
    sys.exit(1 if failures else 0)
