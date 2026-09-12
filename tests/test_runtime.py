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


# --------------------------------------------------------------------------
# contracts that arrive as PDF
# --------------------------------------------------------------------------

def test_pdf_routes_are_reported_and_never_crash():
    from src import ingest
    folder = f"{DATA}/contracts/hospital_2"
    text, meta = ingest.read_contract_file(f"{folder}/master_services_agreement.pdf")
    assert meta["route"] in ("pdf_text_layer", "ocr", "failed")
    if meta["route"] == "pdf_text_layer":
        assert meta["exact"] and "In respect of" in text

    # the dataset's "scanned" PDF turns out to carry a text layer too; it is read exactly
    text, meta = ingest.read_contract_file(f"{folder}/master_services_agreement_scanned.pdf")
    assert meta["route"] == "pdf_text_layer" and meta["exact"]

    # an image-only PDF goes to OCR, or fails with a note saying what to install
    text, meta = ingest.read_contract_file("reports/ocr_demo/scanned_contract.pdf")
    assert meta["route"] in ("ocr", "failed")
    assert meta["exact"] is False and meta["note"]
    assert ingest.ingestion_confidence([meta]) < 1.0

    assert ingest.repair_ocr_numbers("GBP 2S2.SO per hour, S patients") == "GBP 252.50 per hour, S patients"


def test_prose_path_prefers_markdown_and_records_it():
    text, docs = audit.contract_text(f"{DATA}/contracts/hospital_2")
    assert [d["file"] for d in docs] == ["master_services_agreement.md"]
    assert docs[0]["route"] == "text" and docs[0]["exact"]
    assert len(extract.rate_chunks(text)) == 13


def test_hospital_2_loads_identically_from_its_pdf_alone(tmp_path):
    """A provider that sends only a PDF: same articles, same header, same spec."""
    import shutil
    folder = tmp_path / "contracts" / "hospital_2"
    folder.mkdir(parents=True)
    shutil.copy(f"{DATA}/contracts/hospital_2/master_services_agreement.pdf", folder)

    text, docs = audit.contract_text(str(folder))
    assert docs[0]["route"] == "pdf_text_layer"
    chunks = extract.rate_chunks(text)
    assert len(chunks) == 13 and sum(c["n_clauses"] for c in chunks) == 76

    from_pdf = audit.load_spec(str(tmp_path), "hospital_2")
    from_md = audit.load_spec(DATA, "hospital_2")
    for family in ("services", "threshold_premiums", "nbd_uplifts", "volume_discounts"):
        assert from_pdf[family] == from_md[family], family
    assert sorted(from_pdf["bundles"]) == sorted(from_md["bundles"])
    assert from_pdf["contract_number"] == from_md["contract_number"]
    assert from_pdf["provenance"]["documents"][0]["route"] == "pdf_text_layer"


def test_prompt_v2_reads_hospital_2_with_no_defects_on_both_models():
    """The revision was written against gpt-4o's measured confusion; it fixed both models."""
    from evaluation.verify_hospital_2 import verify
    contract = config.CONTRACTS / "hospital_2" / "master_services_agreement.md"
    for model in ("gpt-4o", "deepseek"):
        v1 = audit.load_spec(DATA, "hospital_2", model_name=model, prompt_version="prose_v1")
        v2 = audit.load_spec(DATA, "hospital_2", model_name=model, prompt_version="prose_v2")
        defects_v1, _ = verify(v1, contract, show=False)
        defects_v2, _ = verify(v2, contract, show=False)
        assert len(defects_v1) > 0, model            # v1 was measurably wrong
        assert defects_v2 == [], (model, defects_v2) # v2 is not


def test_rules_summary_counts_are_computed_not_estimated():
    from src import ask as ask_mod
    spec = audit.load_spec(DATA, "hospital_2")
    text = ask_mod.rules_summary(spec)
    assert "services with a daily cap: 8" in text
    assert "bundles: 3 pairs, 6 services" in text
    assert "services with a non-business-day uplift: 8" in text
    assert "services with a threshold premium: 9" in text
    assert text.count("cumulative units") == 12          # 8 discounted services, 12 tiers


def test_quote_prices_the_whole_day_at_the_premium_rate_not_marginally():
    """A model answered 10 x 4225 + 5 x 5281.25. The contract says the day's rate rises."""
    import datetime
    from src.pricing import quote
    spec = audit.load_spec(DATA, "hospital_2")
    saturday = datetime.date(2024, 6, 8)
    q = quote(spec, "Ambulatory Vascular Infusion Therapy", 15, saturday)
    assert q["unit_rate"] == 5281 and q["total"] == 79215
    assert not any("non-business" in label for label, _ in q["steps"])     # 22.2 has no uplift
    assert quote(spec, "Ambulatory Vascular Infusion Therapy", 10, saturday)["total"] == 42250  # "exceeds ten"

    q = quote(spec, "Emergency Renal Infusion Therapy", 3, saturday)           # 4.4: +12% weekend
    assert q["unit_rate"] == 6636 and q["total"] == 3 * 6636
    assert quote(spec, "Emergency Renal Infusion Therapy", 3, datetime.date(2024, 6, 5))["unit_rate"] == 5925

    q = quote(spec, "Emergency Haematology Transport Service", 2, saturday, prior_units=200)  # 8.3: -20% after 180
    assert q["unit_rate"] == 7740
    assert q["assumptions"] == []


def test_retrieval_works_without_sentence_transformers(monkeypatch):
    """The TF-IDF fallback must fit once and search with the same vocabulary."""
    import sys
    from src import retrieval
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)     # force the fallback
    texts = ["4.1 In respect of Advanced Infectious Isolation Room Occupancy, GBP 1,648.25 per day",
             "4.4 In respect of Emergency Renal Infusion Therapy, GBP 59.25 per hour, increased on a non-Business Day",
             "8.3 Emergency Haematology Transport Service, a discount after sixty visits"]
    meta = [{"hospital": "hospital_2"}] * 3
    index = retrieval.VectorIndex(texts, meta)
    assert index.encoder_name.startswith("tfidf")
    hits = index.search("renal infusion weekend rate", k=2, where={"hospital": "hospital_2"})
    assert hits and "Renal" in hits[0]["text"]
    assert index.search("anything", k=1, where={"hospital": "hospital_9"}) == []


def test_a_live_reply_that_is_not_json_is_retried_once():
    chunks, header = _prose_setup()
    replies = iter(["{\"services\": [", '{"services": []}'])          # truncated, then fine

    class Flaky:
        via = "direct"
        def generate(self, s, u):
            return next(replies), {"input_tokens": 1, "output_tokens": 1, "seconds": 0.1, "retries": 0}
    spec, frame, tel = extract.extract_contract(Flaky(), "p", chunks[:1], header, "hospital_2", verbose=False)
    assert tel.parse_error.isna().all() and int(tel.retries.sum()) == 1


def test_repair_model_replays_good_chunks_and_calls_live_for_bad_ones():
    recording = {"0": {"reply": '{"services": []}', "usage": {"input_tokens": 5}},
                 "1": {"reply": '{"services": [', "usage": {"input_tokens": 5}}}

    class Live:
        via = "direct"
        calls = 0
        def generate(self, s, u):
            Live.calls += 1
            return '{"services": []}', {"input_tokens": 9, "output_tokens": 1, "seconds": 0.1, "retries": 0}
    m = llm.RepairModel(recording, Live(), "test")
    r0, u0 = m.generate("s", "u"); r1, u1 = m.generate("s", "u")
    assert u0["telemetry"] == "recorded" and Live.calls == 1 and m.repaired == [1]


def test_cost_and_compare_questions_are_answered_by_the_engine_after_the_model_parses():
    from src import ask as ask_mod
    spec = audit.load_spec(DATA, "hospital_2")

    class Parser:                     # the model's only job here is to fill the JSON
        via = "direct"
        def __init__(self, reply): self.reply = reply
        def generate(self, s, u):
            return self.reply, {"input_tokens": 10, "output_tokens": 5, "seconds": 0.2, "retries": 0}

    class Idx:
        encoder_name = "stub"
        def search(self, *a, **k): return []

    cost = Parser('{"kind":"cost","service":"Ambulatory Vascular Infusion Therapy","quantity":15,"date":"2024-06-08"}')
    r = ask_mod.answer("what would 15 hours cost on Saturday?", Idx(), cost, "hospital_2", spec=spec)
    assert r["route"] == "engine-cost" and "79,215 cents" in r["answer"] and "5,281" in r["answer"]

    cmp = Parser('{"kind":"compare","services":["Standard Orthopaedic Isolation Room Occupancy","Continuous Renal Ventilation Support"]}')
    r = ask_mod.answer("which is more expensive?", Idx(), cmp, "hospital_2", spec=spec)
    assert r["route"] == "engine-compare" and "Continuous Renal Ventilation Support is more expensive" in r["answer"]

    bad = Parser('{"kind":"cost","service":"Made Up Service","quantity":3}')      # falls back to the model path
    r = ask_mod.answer("cost of made up service?", Idx(), bad, "hospital_2", spec=spec, table=None)
    assert r["route"] == "model"
