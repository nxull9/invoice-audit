"""Audit one hospital end to end: contract -> spec -> resolve -> reprice -> findings.

`load_spec` is the one place that decides how a contract is read. Tables are read by
regex; prose is read by a model, from a recording when one exists so the result is
reproducible without a key. Everything after that point is identical for every hospital.
"""

import glob

import pandas as pd

from src import checks, config
from src.classify import classify, expected_totals
from src.compile_contract import COMPILERS, compile_contract
from src.contracts import read_header
from src.data import build_invoice_units, load_invoices, load_line_items
from src.extract import extract_contract, rate_chunks
from src.ingest import ingestion_confidence, read_contract_file
from src.llm import ApiModel, ReplayModel, load_recording, save_recording
from src.pricing import reprice
from src.resolver import resolve


def load_spec(data_root, hospital, model_name=None, prompt_version=None, live=False,
              verbose=False):
    """The contract spec for a hospital.

    A hospital with a table compiler is read by regex. Any other hospital is prose and
    is read by a model: replayed from `runs/` if that model and prompt were run before,
    otherwise called live (needs a key) and recorded for next time. `live=True` forces
    a fresh call.
    """
    if hospital in COMPILERS:
        return compile_contract(data_root, hospital)
    return extract_prose_contract(data_root, hospital, model_name, prompt_version, live,
                                  verbose)


def extract_prose_contract(data_root, hospital, model_name=None, prompt_version=None,
                           live=False, verbose=False):
    model_name = model_name or config.EXTRACTION_MODEL
    prompt_version = prompt_version or config.PROSE_PROMPT_VERSION

    text, documents = contract_text(f"{data_root}/contracts/{hospital}")
    chunks = rate_chunks(text)
    if not chunks:
        raise ValueError(f"{hospital}: no rate-bearing articles found in "
                         f"{[d['file'] for d in documents]} (read via {documents[0]['route']}); "
                         "the prose reader needs the contract's article headings")

    prompt = open(config.PROMPTS / f"contract_extraction_{prompt_version}.txt").read()
    header = read_header(data_root, hospital)

    recording = None if live else load_recording(model_name, prompt_version, hospital)
    if recording is not None:
        model, record = ReplayModel(recording, model_name), None
    else:
        model, record = ApiModel(model_name), {}

    spec, frame, telemetry = extract_contract(model, prompt, chunks, header, hospital,
                                              verbose=verbose or record is not None,
                                              record=record)
    if record:
        save_recording(record, model_name, prompt_version, hospital)

    spec["provenance"].update({
        "documents": documents,
        "model": model_name,
        "prompt_version": prompt_version,
        "replayed": recording is not None,
        "confidence": config.MODEL_EXTRACTION_CONFIDENCE * ingestion_confidence(documents),
        "chunks": len(chunks),
        "clauses_expected": int(sum(c["n_clauses"] for c in chunks)),
        "services_accepted": int(telemetry.services_accepted.sum()),
        "parse_failures": int(telemetry.parse_error.notna().sum()),
    })
    spec["extraction_frame"] = frame
    return spec


def contract_text(folder):
    """The text of a prose contract and how it was obtained.

    Markdown is exact and carries the headings the chunker needs, so it wins. Plain text
    is next. A PDF is read last -- its text layer if it has one, OCR if it does not --
    and the route is recorded so a rate read by OCR is never trusted as exact.
    """
    for pattern in ("*.md", "*.txt", "*.pdf"):
        paths = sorted(glob.glob(f"{folder}/{pattern}"))
        if not paths:
            continue
        texts, provenance = [], []
        for path in paths:
            text, meta = read_contract_file(path)
            if text:
                texts.append(text)
            provenance.append(meta)
        if texts:
            return "\n\n".join(texts), provenance
    raise FileNotFoundError(f"no readable contract document in {folder}")


def unknown_service_findings(resolution, line_items):
    """Invoices carrying a description that resolves to no contracted service."""
    unknown = set(resolution.loc[resolution["method"] == "unknown_service", "description"])
    hit = line_items[line_items["description"].isin(unknown)]
    return pd.DataFrame([
        {"invoice_id": r.invoice_id, "category": "unknown_service",
         "detail": f"{r.line_id}: {r.description!r} matches no contracted service"}
        for r in hit.itertuples()
    ], columns=["invoice_id", "category", "detail"])


def audit_hospital(data_root, hospital, spec=None, **spec_options):
    """Every check for one hospital. Returns the pieces the report and the app need.

    `spec` may be supplied directly (a test injects a known spec); otherwise it is
    loaded by `load_spec` with any `spec_options` passed through.
    """
    header = read_header(data_root, hospital)
    if spec is None:
        spec = load_spec(data_root, hospital, **spec_options)
    invoices = load_invoices(data_root, hospital)
    line_items = load_line_items(data_root, hospital)
    units = build_invoice_units(invoices, line_items)

    resolution = resolve(spec, line_items)
    priced = reprice(spec, units, line_items, resolution)

    findings = pd.concat([
        checks.run_all(units, line_items, header),
        unknown_service_findings(resolution, line_items),
        classify(priced, spec),
    ], ignore_index=True)
    findings = findings.groupby(["invoice_id", "category"], as_index=False).agg(
        detail=("detail", "first"), n_lines=("detail", "size"))

    return {"hospital": hospital, "header": header, "spec": spec, "units": units,
            "line_items": line_items, "resolution": resolution, "priced": priced,
            "findings": findings, "totals": expected_totals(priced, units)}


def hospital_of(invoice_id):
    """'INV-H3-000142' -> 'hospital_3', or None if the id is not in that form."""
    parts = invoice_id.upper().split("-")
    if len(parts) >= 2 and parts[1].startswith("H") and parts[1][1:].isdigit():
        return f"hospital_{int(parts[1][1:])}"
    return None
