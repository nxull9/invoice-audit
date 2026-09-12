"""Ask a question about a contract, answered from retrieved clauses.

Interactive counterpart to the batch extraction. The model only ever sees clauses
retrieved from one hospital's contract, so an answer cannot be drawn from another
hospital's terms or from the model's own recollection, and every answer carries the
clauses it was based on.
"""

import glob
import os
import re
import textwrap

from src.config import PROMPTS
from src.retrieval import VectorIndex

QA_PROMPT_VERSION = "qa_v3"
EXPLANATION_PROMPT_VERSION = "explanation_v1"


def answer_prompt():
    return open(PROMPTS / f"contract_{QA_PROMPT_VERSION}.txt").read()



def clause_index(data_root, hospital, encoder=None):
    """Split a hospital's contract into clauses and index them for retrieval."""
    clauses, meta = [], []
    for path in sorted(glob.glob(f"{data_root}/contracts/{hospital}/*.md")):
        document = os.path.basename(path)
        text = open(path).read()
        section = "preamble"
        for block in re.split(r"\n(?=#{2,3} |\d+\.\d+ |[A-Z]\d\.\d )", text):
            block = block.strip()
            if len(block) < 40:
                continue
            heading = block.splitlines()[0]
            if heading.startswith("#"):
                section = heading.lstrip("# ").strip()
            clauses.append(block[:1800])
            meta.append({"hospital": hospital, "document": document, "section": section})
    return VectorIndex(clauses, meta, encoder), clauses


TABLE_COLUMNS = ["service", "unit_basis", "rate_cents", "daily_cap", "nbd_uplift_pct",
                 "premium_threshold", "premium_uplift_pct", "discount_threshold",
                 "discount_pct", "bundle_partner"]


def rules_summary(spec):
    """Counts and lists per rule family, computed in Python.

    A model reading an 80-row CSV counted 8 capped services as 5 and listed 4 of 6
    bundled services. Counting is arithmetic; it is done here and handed over as fact.
    """
    svc = spec["services"]
    caps = sorted((n, v["daily_cap"]) for n, v in svc.items() if v["daily_cap"] is not None)
    nbd = sorted((n, f) for n, f in spec["nbd_uplifts"].items())
    prem = sorted((n, t, f) for n, (t, f) in spec["threshold_premiums"].items())
    disc = sorted((n, tiers) for n, tiers in spec["volume_discounts"].items())
    pct = lambda f: f"{float(f) * 100:g}%"
    lines = [
        f"services: {len(svc)}",
        f"services with a daily cap: {len(caps)}",
        *[f"  - {n}: cap {c} per patient per Service Day" for n, c in caps],
        f"services with a non-business-day uplift: {len(nbd)}",
        *[f"  - {n}: +{pct(f)} on a Saturday or Sunday" for n, f in nbd],
        f"services with a threshold premium: {len(prem)}",
        *[f"  - {n}: +{pct(f)} when more than {t} units in one Service Day" for n, t, f in prem],
        f"services with a volume discount: {len(disc)}",
        *[f"  - {n}: " + "; ".join(f"-{pct(f)} after {t} cumulative units" for t, f in sorted(tiers))
          for n, tiers in disc],
        f"bundles: {len(spec['bundles'])} pairs, {2 * len(spec['bundles'])} services",
        *[f"  - {a} ({svc[a]['rates'][0]['cents']} -> {ra} cents) with {b} ({svc[b]['rates'][0]['cents']} -> {rb} cents)"
          for a, b, ra, rb in spec["bundles"]],
        f"services with none of these rules: {len([n for n in svc if n not in dict(caps) and n not in spec['nbd_uplifts'] and n not in spec['threshold_premiums'] and n not in spec['volume_discounts'] and not any(n in pair[:2] for pair in spec['bundles'])])}",
    ]
    return "\n".join(lines)


def rules_table_text(table):
    """The hospital's rules as compact CSV, blank where a rule does not apply."""
    cols = [c for c in TABLE_COLUMNS if c in table.columns]
    return table[cols].to_csv(index=False, na_rep="")


def ask(question, index, model, hospital, k=4, show_context=True, table=None, spec=None):
    """Answer from one hospital's contract: its rules table plus the k most relevant clauses.

    The table carries every service, so questions across services (which, how many,
    compare) can be answered; the clauses carry the wording, so single-service questions
    can be quoted. Neither includes any other hospital.
    """
    hits = index.search(question, k=k, where={"hospital": hospital})
    if not hits and table is None:
        return "No clauses retrieved for that hospital."

    clauses = "\n\n".join(
        f"[{i + 1}] ({h['document']} · {h['section']})\n{h['text']}"
        for i, h in enumerate(hits))
    parts = []
    if spec is not None:
        parts.append(f"SUMMARY (counts and lists computed by the audit engine; authoritative):\n{rules_summary(spec)}")
    if table is not None:
        parts.append(f"RULES TABLE ({len(table)} rows):\n{rules_table_text(table)}")
    parts.append(f"CLAUSES:\n{clauses}")
    answer, usage = model.generate(answer_prompt(),
                                   "\n\n".join(parts) + f"\n\nQUESTION: {question}")

    if show_context:
        print(f"question  {question}")
        print(f"hospital  {hospital}   clauses retrieved: {len(hits)}")
        for i, h in enumerate(hits):
            print(f"   [{i + 1}] {h['score']:.3f}  {h['section'][:60]}")
        print()
    print(textwrap.fill(answer, 92, subsequent_indent="  "))
    print()
    print(f"[{usage['input_tokens']} in · {usage['output_tokens']} out · {usage['seconds']}s]")
    return answer


RELEVANT = 0.35     # below this the best clause is unrelated to the question


def ask_every_hospital(question, indexes, model, k=4):
    """Ask each hospital's contract separately; answer only from those with a match.

    Contracts are never mixed in one prompt. A question about "the MRI rate" gets one
    answer per hospital whose clauses mention it, each grounded in its own contract,
    and silence from the rest.
    """
    answered = []
    for hospital, index in indexes.items():
        hits = index.search(question, k=1, where={"hospital": hospital})
        if not hits or hits[0]["score"] < RELEVANT:
            continue
        print(f"===== {hospital} =====")
        ask(question, index, model, hospital, k=k)
        answered.append(hospital)
    if not answered:
        print("No contract has a clause close to that question.")
    return answered


def explain_with_model(explanation, model):
    """Narrate a deterministic audit result in plain English. The model adds no facts."""
    e = explanation
    lines = [f"hospital: {e['hospital']}", f"invoice: {e['invoice_id']}  dated {e['invoice_date']}",
             f"contract read from: {e['contract_source']}",
             f"billed_total_cents: {e['billed_total_cents']}",
             f"expected_total_cents: {e['expected_total_cents']}",
             f"flagged: {e['flagged']}  categories: {', '.join(e['categories']) or 'none'}",
             f"confidence: {e['confidence']}", "evidence:"]
    lines += [f"  - {x}" for x in e["evidence"]] or ["  - none"]
    lines.append("line items (id, date, description -> service, qty x billed rate, expected rate, adjustments):")
    for l in e["lines"]:
        lines.append(f"  - {l['line_id']} {l['service_date']} {l['description']!r} -> {l['service']}: "
                     f"{l['qty']} x {l['billed_rate']}, expected {l['expected_rate']}, {l['adjustments'] or '-'}")
    prompt = open(PROMPTS / f"invoice_{EXPLANATION_PROMPT_VERSION}.txt").read()
    answer, usage = model.generate(prompt, "\n".join(lines))
    print(textwrap.fill(answer, 92, subsequent_indent="  "))
    print(f"\n[{usage['input_tokens']} in · {usage['output_tokens']} out · {usage['seconds']}s]")
    return answer
