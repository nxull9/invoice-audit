"""Ask a question about a contract, answered from retrieved clauses.

Interactive counterpart to the batch extraction. The model only ever sees clauses
retrieved from one hospital's contract, so an answer cannot be drawn from another
hospital's terms or from the model's own recollection, and every answer carries the
clauses it was based on.
"""

import datetime
import glob
import os
import re
import textwrap

from src.config import PROMPTS
from src.llm import parse_json
from src.pricing import quote
from src.retrieval import VectorIndex

QA_PROMPT_VERSION = "qa_v5"
PARSE_PROMPT_VERSION = "parse_v1"
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


TABLE_COLUMNS = ["service", "unit_basis", "rate_cents", "valid_from", "valid_to", "daily_cap",
                 "nbd_uplift_pct", "premium_threshold", "premium_uplift_pct", "discount_threshold",
                 "discount_pct", "bundle_partner", "bundle_rate_cents",
                 "facility_multipliers", "tier_multipliers"]


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
        "computed answers (use these for highest / largest / most / cheapest / ties):",
        *_superlatives(spec, caps, nbd, prem, disc),
        f"exclusion windows: {len(spec['exclusions'])}",
        *[f"  - {excluded} is not billable within {days} days of {trigger} (either direction)"
          for excluded, days, trigger in spec["exclusions"]],
        f"services with facility multipliers: {len(spec['facility_multipliers'])}; "
        f"with plan-tier multipliers: {len(spec['tier_multipliers'])}"
        + (" (the multipliers themselves are in the RULES TABLE columns facility_multipliers / tier_multipliers)"
           if spec["facility_multipliers"] or spec["tier_multipliers"] else ""),
        f"services with none of these rules: {len([n for n in svc if n not in dict(caps) and n not in spec['nbd_uplifts'] and n not in spec['threshold_premiums'] and n not in spec['volume_discounts'] and not any(n in pair[:2] for pair in spec['bundles'])])}",
    ]
    return "\n".join(lines)


def _superlatives(spec, caps, nbd, prem, disc):
    """Pre-computed extremes, with every service that ties, so the model copies them."""
    svc = spec["services"]
    pct = lambda f: f"{float(f) * 100:g}%"
    out = []
    if caps:
        top = max(c for _, c in caps); low = min(c for _, c in caps)
        out.append(f"  - highest daily cap: {top} ({', '.join(n for n, c in caps if c == top)})")
        out.append(f"  - lowest daily cap: {low} ({', '.join(n for n, c in caps if c == low)})")
    if nbd:
        top = max(f for _, f in nbd)
        out.append(f"  - largest non-business-day uplift: {pct(top)} ({', '.join(n for n, f in nbd if f == top)})")
    if prem:
        top = max(f for _, _, f in prem)
        out.append(f"  - largest threshold premium: {pct(top)} ({', '.join(n for n, _, f in prem if f == top)})")
    if disc:
        deepest = max(f for _, tiers in disc for _, f in tiers)
        out.append(f"  - deepest volume discount: {pct(deepest)} ({', '.join(n for n, tiers in disc if any(f == deepest for _, f in tiers))})")
        multi = [n for n, tiers in disc if len(tiers) >= 2]
        out.append(f"  - services with two or more discount tiers: {len(multi)} ({', '.join(multi) or 'none'})")
    rates = sorted((v["rates"][0]["cents"], n) for n, v in svc.items())
    out.append(f"  - most expensive service by unit rate: {rates[-1][1]} at {rates[-1][0]} cents {svc[rates[-1][1]]['unit_basis']}")
    out.append(f"  - cheapest service by unit rate: {rates[0][1]} at {rates[0][0]} cents {svc[rates[0][1]]['unit_basis']}")
    return out


def rules_table_text(table):
    """The hospital's rules as compact CSV, blank where a rule does not apply."""
    cols = [c for c in TABLE_COLUMNS if c in table.columns]
    return table[cols].to_csv(index=False, na_rep="")


def build_context(question, index, hospital, k=4, table=None, spec=None):
    """What the model is shown for one question: summary, table, retrieved clauses."""
    hits = index.search(question, k=k, where={"hospital": hospital})
    clauses = "\n\n".join(
        f"[{i + 1}] ({h['document']} · {h['section']})\n{h['text']}"
        for i, h in enumerate(hits))
    parts = []
    if spec is not None:
        parts.append("SUMMARY (counts and lists computed by the audit engine; authoritative):\n"
                     + rules_summary(spec))
    if table is not None:
        parts.append(f"RULES TABLE ({len(table)} rows):\n{rules_table_text(table)}")
    parts.append(f"CLAUSES:\n{clauses}")
    return "\n\n".join(parts) + f"\n\nQUESTION: {question}", hits


def parse_question(question, spec, model):
    """Ask the model what kind of question this is and, for a cost or comparison, the inputs.

    The model interprets; it does not compute. A reply that is not valid, or that names a
    service not in the contract, is treated as "other" and answered the ordinary way.
    """
    system = open(PROMPTS / f"question_{PARSE_PROMPT_VERSION}.txt").read()
    names = "\n".join(sorted(spec["services"]))
    text, usage = model.generate(system, f"SERVICES:\n{names}\n\nQUESTION: {question}")
    payload, error = parse_json(text)
    if error or not isinstance(payload, dict):
        return {"kind": "other", "note": f"parse failed: {error}"}, usage
    kind = payload.get("kind")
    if kind == "cost" and payload.get("service") in spec["services"] and isinstance(payload.get("quantity"), int) and payload["quantity"] > 0:
        return payload, usage
    if kind == "compare" and isinstance(payload.get("services"), list) and len(payload["services"]) == 2 \
            and all(n in spec["services"] for n in payload["services"]):
        return payload, usage
    return {"kind": "other", "note": f"unusable parse: {payload}"}, usage


def _date(value, default=None):
    try:
        return datetime.date.fromisoformat(str(value)[:10]) if value else default
    except ValueError:
        return default


def cost_answer(spec, parsed):
    """The engine prices the line; the text just shows its steps."""
    q = quote(spec, parsed["service"], parsed["quantity"], _date(parsed.get("date"), datetime.date(2024, 6, 5)),
              facility_code=parsed.get("facility_code") or None, plan_tier=parsed.get("plan_tier") or None,
              prior_units=parsed.get("prior_units") or 0, with_partner=bool(parsed.get("with_partner")))
    steps = "; ".join(f"{label} -> {value:,} cents" for label, value in q["steps"])
    assumed = ("; assumed: " + "; ".join(q["assumptions"])) if q["assumptions"] else ""
    return (f"ANSWER: {q['total']:,} cents (GBP {q['total'] / 100:,.2f}) for {q['billable']} x {parsed['service']} "
            f"at a unit rate of {q['unit_rate']:,} cents. Steps: {steps}{assumed}.  "
            f"SOURCE: audit engine (deterministic)  QUOTE: n/a")


def compare_answer(spec, parsed):
    a, b = parsed["services"]
    ra, rb = spec["services"][a]["rates"][0]["cents"], spec["services"][b]["rates"][0]["cents"]
    ua, ub = spec["services"][a]["unit_basis"], spec["services"][b]["unit_basis"]
    if ra == rb:
        verdict = "They cost the same per unit"
    else:
        hi = a if ra > rb else b
        verdict = f"{hi} is more expensive per unit"
    note = "" if ua == ub else f" (note the unit bases differ: {ua} vs {ub})"
    return (f"ANSWER: {a} = {ra:,} cents {ua}; {b} = {rb:,} cents {ub}. {verdict}{note}.  "
            f"SOURCE: table  QUOTE: n/a")


def answer(question, index, model, hospital, k=4, table=None, spec=None, prompt_version=None):
    """Answer one question from one hospital's contract. Returns a dict, prints nothing.

    A question asking what something costs, or which of two services is dearer, is
    parsed by the model and answered by the engine. Everything else is answered by the
    model from the summary, the table and the retrieved clauses.
    """
    route, total_usage = "model", None
    if spec is not None:
        parsed, pusage = parse_question(question, spec, model)
        total_usage = dict(pusage)
        if parsed["kind"] == "cost":
            return {"answer": cost_answer(spec, parsed), "usage": total_usage, "hits": [],
                    "hospital": hospital, "route": "engine-cost", "parsed": parsed}
        if parsed["kind"] == "compare":
            return {"answer": compare_answer(spec, parsed), "usage": total_usage, "hits": [],
                    "hospital": hospital, "route": "engine-compare", "parsed": parsed}
    user, hits = build_context(question, index, hospital, k, table, spec)
    system = open(PROMPTS / f"contract_{prompt_version or QA_PROMPT_VERSION}.txt").read()
    text, usage = model.generate(system, user)
    if total_usage:
        for key in ("input_tokens", "output_tokens", "seconds"):
            usage[key] = round(usage.get(key, 0) + total_usage.get(key, 0), 2)
    return {"answer": text, "usage": usage, "hits": hits, "hospital": hospital, "route": route}


def ask(question, index, model, hospital, k=4, show_context=True, table=None, spec=None,
        prompt_version=None):
    """Answer from one hospital's contract and print it: the computed summary, the rules
    table and the k most relevant clauses go to the model; nothing from another hospital."""
    result = answer(question, index, model, hospital, k, table, spec, prompt_version)
    hits, usage, text = result["hits"], result["usage"], result["answer"]
    if not hits and table is None:
        print("No clauses retrieved for that hospital.")
        return text
    if show_context:
        print(f"question  {question}")
        print(f"hospital  {hospital}   clauses retrieved: {len(hits)}")
        for i, h in enumerate(hits):
            print(f"   [{i + 1}] {h['score']:.3f}  {h['section'][:60]}")
        print()
    print(textwrap.fill(text, 92, subsequent_indent="  "))
    print()
    print(f"[{usage['input_tokens']} in · {usage['output_tokens']} out · {usage['seconds']}s]")
    return text


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
