"""Tests for the runtime entry points: loading a spec, writing a submission, composing
confidence, and failing safely when a model misbehaves.

Run with:  python -m pytest tests -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest
import requests

from src import audit, config, extract, llm, output

DATA = str(config.DATA)


# --------------------------------------------------------------------------
# loading specs
# --------------------------------------------------------------------------

def test_hospital_is_read_from_the_invoice_id():
    assert audit.hospital_of("INV-H3-000142") == "hospital_3"
    assert audit.hospital_of("inv-h5-000001") == "hospital_5"
    assert audit.hospital_of("banana") is None
    assert audit.hospital_of("INV-HX-1") is None


def test_hospital_2_replays_the_shipped_recording_without_a_key():
    os.environ.pop("OPENROUTER_API_KEY", None)
    spec = audit.load_spec(DATA, "hospital_2")
    prov = spec["provenance"]
    assert prov["replayed"] is True
    assert prov["model"] == config.EXTRACTION_MODEL
    assert prov["parse_failures"] == 0
    assert len(spec["services"]) == 76 == prov["clauses_expected"]
    assert output.extraction_confidence(spec) == config.MODEL_EXTRACTION_CONFIDENCE


def test_tabular_hospitals_carry_full_extraction_confidence():
    for h in ["hospital_1", "hospital_3", "hospital_4", "hospital_5"]:
        assert output.extraction_confidence(audit.load_spec(DATA, h)) == 1.0


# --------------------------------------------------------------------------
# submission
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hospital_1():
    return audit.audit_hospital(DATA, "hospital_1")


def test_submission_rows_validate_and_cover_every_invoice(hospital_1):
    rows = output.submission_rows(hospital_1)
    ids = set(hospital_1["units"]["invoice_id"])
    assert output.validate_submission(rows, expected_ids=ids) == []
    assert list(rows.columns) == output.SUBMISSION_COLUMNS
    assert rows["invoice_id"].is_unique and set(rows["invoice_id"]) == ids
    assert rows["flagged"].sum() == 58


def test_validation_catches_each_way_a_submission_can_be_wrong(hospital_1):
    good = output.submission_rows(hospital_1)

    broken = pd.concat([good, good.iloc[[0]]])
    assert any("duplicate" in p for p in output.validate_submission(broken))

    broken = good.copy(); broken.loc[0, "flagged"] = 2
    assert any("flagged" in p for p in output.validate_submission(broken))

    broken = good.copy(); broken.loc[0, "confidence"] = 1.5
    assert any("confidence" in p for p in output.validate_submission(broken))

    broken = good.copy(); broken["expected_total_cents"] = broken["expected_total_cents"].astype(float)
    assert any("integer" in p for p in output.validate_submission(broken))

    broken = good.copy()
    first_flagged = broken.index[broken["flagged"] == 1][0]
    broken.loc[first_flagged, "error_category"] = ""
    assert any("no error_category" in p for p in output.validate_submission(broken))

    broken = good.drop(columns=["confidence"])
    assert any("columns" in p for p in output.validate_submission(broken))

    assert any("missing" in p for p in output.validate_submission(good, expected_ids=set(good.invoice_id) | {"INV-H1-999999"}))


def test_reused_identifiers_report_the_later_invoice(hospital_1):
    totals = hospital_1["totals"]
    reused = totals[totals.duplicated("invoice_id", keep=False)]
    assert len(reused) == 10                         # five identifiers, two invoices each
    collapsed = output.collapse_reused_ids(totals)
    for invoice_id, group in reused.groupby("invoice_id"):
        later = group.sort_values("source_seq").iloc[-1]
        assert collapsed.loc[collapsed.invoice_id == invoice_id, "source_seq"].item() == later.source_seq


# --------------------------------------------------------------------------
# confidence
# --------------------------------------------------------------------------

def test_confidence_is_composed_from_evidence():
    arithmetic = ["line_total_arithmetic", "invoice_total_mismatch"]
    # arithmetic facts are certain whoever read the contract and however it was resolved
    assert output.invoice_confidence(arithmetic, 0.85, 0.40) == 1.0
    # a rule-based finding is weakened by a model-read contract and a shaky resolution
    assert output.invoice_confidence(["premium_omitted"], 1.0, 0.98) == round(0.85 * 0.98, 3)
    assert output.invoice_confidence(["premium_omitted"], 0.85, 0.98) == round(0.85 * 0.85 * 0.98, 3)
    assert output.invoice_confidence(["premium_omitted"], 0.85, 0.40) < 0.30
    # the weakest category sets the ceiling
    assert output.invoice_confidence(["line_total_arithmetic", "daily_cap_exceeded"], 1.0, 1.0) == 0.75
    # a clean invoice is never certain, and less so under a model-read contract
    assert output.invoice_confidence([], 1.0, 0.98) == round(0.95 * 0.98, 3)
    assert output.invoice_confidence([], 0.85, 0.98) < output.invoice_confidence([], 1.0, 0.98)


def test_clean_invoices_under_the_model_read_contract_are_less_confident():
    h2 = output.submission_rows(audit.audit_hospital(DATA, "hospital_2"))
    h4 = output.submission_rows(audit.audit_hospital(DATA, "hospital_4"))
    assert h2.loc[h2.flagged == 0, "confidence"].mean() < h4.loc[h4.flagged == 0, "confidence"].mean()


# --------------------------------------------------------------------------
# a model behaving badly
# --------------------------------------------------------------------------

def _prose_setup():
    text = open(f"{DATA}/contracts/hospital_2/master_services_agreement.md").read()
    chunks = extract.rate_chunks(text)[:2]
    from src.contracts import read_header
    return chunks, read_header(DATA, "hospital_2")


def test_malformed_replies_become_warnings_not_crashes():
    chunks, header = _prose_setup()
    model = llm.ReplayModel({"0": "I am a language model and cannot help.",
                             "1": '{"services": [{"service": 1, "rate_cents": "x"}]}'})
    spec, frame, tel = extract.extract_contract(model, "p", chunks, header, "hospital_2", verbose=False)
    assert len(spec["services"]) == 0
    assert tel.parse_error.notna().sum() == 1
    assert len(spec["warnings"]) >= 2


def test_missing_fields_and_invented_services_are_rejected():
    chunks, _ = _prose_setup()
    text = chunks[0]["text"]
    real = "Advanced Infectious Isolation Room Occupancy"
    ok = {"service": real, "unit_basis": "per day of service", "rate_cents": 164825, "source_quote": ""}
    assert extract.validate_service(ok, text)[0] is not None

    for bad, reason in [({"service": ""}, "no service name"),
                        ({"rate_cents": None}, "no usable rate"),
                        ({"rate_cents": 0}, "no usable rate"),
                        ({"unit_basis": "per fortnight"}, "unit basis"),
                        ({"service": "Invented Quantum Therapy"}, "does not appear")]:
        rec, problems = extract.validate_service({**ok, **bad}, text)
        assert rec is None and any(reason in p for p in problems), (bad, problems)


def test_a_rule_naming_an_unextracted_partner_is_a_warning():
    chunks, header = _prose_setup()
    reply = ('{"services": [{"service": "Advanced Infectious Isolation Room Occupancy", '
             '"unit_basis": "per_day", "rate_cents": 164825, "source_quote": "", '
             '"bundle": {"partner_service": "Nobody", "this_rate_cents": 1, "partner_rate_cents": 2}}]}')
    spec, *_ = extract.extract_contract(llm.ReplayModel({"0": reply}), "p", chunks[:1], header,
                                        "hospital_2", verbose=False)
    assert spec["bundles"] == []
    assert any("Nobody" in w for w in spec["warnings"])


class _FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.text = str(body)

    def json(self):
        return self._body


def _ok_reply(text='{"services": []}'):
    return _FakeResponse(200, {"choices": [{"message": {"content": text}}],
                              "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def test_api_client_retries_transient_failures_and_raises_on_bad_credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    model = llm.ApiModel("gpt-4o")

    calls = iter([_FakeResponse(429, headers={"Retry-After": "0"}),
                  _FakeResponse(503),
                  _ok_reply()])
    monkeypatch.setattr(model.session, "post", lambda *a, **k: next(calls))
    reply, usage = model.generate("s", "u")
    assert reply == '{"services": []}' and usage["retries"] == 2

    monkeypatch.setattr(model.session, "post", lambda *a, **k: _FakeResponse(401, {"error": "bad key"}))
    with pytest.raises(RuntimeError):
        model.generate("s", "u")

    def timeout(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(model.session, "post", timeout)
    with pytest.raises(RuntimeError, match="failed after"):
        model.generate("s", "u")


def test_api_client_needs_a_credential(monkeypatch):
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="No credential"):
        llm.ApiModel("gpt-4o")


# --------------------------------------------------------------------------
# the refactor changed nothing
# --------------------------------------------------------------------------

def test_outputs_match_the_pre_refactor_baseline():
    from evaluation import regression
    assert regression.run() == 0
