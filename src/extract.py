"""Convert a model's JSON extraction into a contract spec.

Every field is validated on the way in and rejected rather than coerced. The prompt
requires a verbatim quote of the clause each rate came from; that quote is checked
against the source text, so a fabricated rule cannot pass.
"""

import re
from decimal import Decimal

from src.config import UNIT_BASIS
from src.contracts import new_spec, new_service, new_rate
from src.llm import parse_json
from src.markdown_tables import sections


# --------------------------------------------------------------------------
# Splitting a prose contract into units a model reads one at a time
# --------------------------------------------------------------------------

RATE_ARTICLE = "Contracted Services"
CLAUSE = re.compile(r"^\d+\.\d+ In respect of", re.M)


def rate_chunks(text, marker=RATE_ARTICLE):
    """The articles that carry rates, as [{title, text, n_clauses}].

    Articles are chosen by heading, not by similarity search: every rate-bearing
    article is needed, and top-k retrieval cannot promise that. `n_clauses` is counted
    by regex so a model that returns fewer has visibly missed some.
    """
    chunks = [{"title": title, "text": body.strip(), "n_clauses": len(CLAUSE.findall(body))}
              for title, body in sections(text).items()
              if marker.lower() in title.lower()]
    return chunks or clause_chunks(text)


def clause_chunks(text):
    """Group clauses by article number when the headings are gone.

    A PDF's text layer keeps "4.1 In respect of ..." but not the markdown heading above
    it. The article number is the first part of the clause number, so the clauses can
    still be gathered into the same thirteen articles a model reads one at a time.
    """
    starts = [m.start() for m in CLAUSE.finditer(text)]
    if not starts:
        return []
    by_article = {}
    for a, b in zip(starts, starts[1:] + [len(text)]):
        clause = text[a:b].strip()
        article = clause.split(".", 1)[0]
        by_article.setdefault(article, []).append(clause)
    return [{"title": f"Article {article}", "text": "\n\n".join(clauses), "n_clauses": len(clauses)}
            for article, clauses in by_article.items()]

VALID_BASES = set(UNIT_BASIS.values())

# The contracts write "per item supplied"; the invoices write "per_item". The enum
# follows the invoice, which is arbitrary from the model's point of view -- a model
# transliterating the contract's own wording is being more faithful to the source than
# the schema is, and rejecting it measures the schema rather than the extraction.
BASIS_ALIASES = {}
for _phrase, _canonical in UNIT_BASIS.items():
    BASIS_ALIASES[_canonical] = _canonical
    BASIS_ALIASES[_phrase] = _canonical
    BASIS_ALIASES[_phrase.replace(" ", "_").replace(",", "")] = _canonical
    BASIS_ALIASES[_phrase.replace(", ", "_").replace(" ", "_")] = _canonical


def canonical_basis(value):
    """Map any wording of a unit basis onto the invoice vocabulary, or None."""
    if not value:
        return None
    key = str(value).strip().lower()
    if key in BASIS_ALIASES:
        return BASIS_ALIASES[key]
    return BASIS_ALIASES.get(key.replace(" ", "_").replace(",", ""))


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        return int(digits) if digits else None
    return None


def _pct(value):
    """20 or "20%" or 0.2 -> Decimal('0.20')."""
    n = _as_int(value) if not isinstance(value, float) else value
    if n is None:
        return None
    d = Decimal(str(n))
    return d / Decimal(100) if d > 1 else d


def _flatten(text):
    """Collapse whitespace and punctuation so a quote can be compared on substance."""
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def parse_day(value):
    """'2025-01-01' -> date, anything unusable -> None."""
    from datetime import date as _date
    if not value or not isinstance(value, str):
        return None
    try:
        y, m, d = (int(x) for x in value.strip()[:10].split("-"))
        return _date(y, m, d)
    except (ValueError, TypeError):
        return None


def _read_rates(item):
    """Read a rate under any of the three prompt schemas.

    v1 stated one rate and could not express hospital 3's amended services. v2 used a
    nested list, which the local model handled badly. v3 returns to flat scalars with
    an optional second rate and its start date. All three are read so recordings made
    under any prompt stay replayable and the versions can be compared directly.
    """

    # v3: flat scalars. A nested list costs small models heavily -- Qwen2.5-7B returned
    # every row under a flat schema and dropped 40% under a nested one, while the three
    # hosted models were unaffected. The date logic belongs in code, not in the schema.
    flat = _as_int(item.get("rate_cents"))
    later = _as_int(item.get("rate_cents_after"))
    changes = parse_day(item.get("rate_change_date"))
    if flat and flat > 0 and later and later > 0 and changes:
        from datetime import timedelta
        return [{"cents": flat, "valid_from": None, "valid_to": changes - timedelta(days=1)},
                {"cents": later, "valid_from": changes, "valid_to": None}]

    listed = item.get("rates")
    if isinstance(listed, list) and listed:
        out = []
        for entry in listed:
            if not isinstance(entry, dict):
                continue
            cents = _as_int(entry.get("rate_cents", entry.get("cents")))
            if cents and cents > 0:
                out.append({"cents": cents,
                            "valid_from": parse_day(entry.get("valid_from")),
                            "valid_to": parse_day(entry.get("valid_to"))})
        return out

    cents = _as_int(item.get("rate_cents"))
    return [{"cents": cents, "valid_from": None, "valid_to": None}] if cents and cents > 0 else []


def validate_service(item, source_text=None):
    """Check one extracted service. Returns (record, [reasons rejected])."""
    problems = []
    name = str(item.get("service") or "").strip()      # a model may return a number here
    if not name:
        return None, ["no service name"]

    raw_basis = str(item.get("unit_basis") or "").strip()
    basis = canonical_basis(raw_basis)
    if basis is None:
        problems.append(f"unit_basis {raw_basis!r} is not a recognised unit basis")

    rates = _read_rates(item)
    if not rates:
        problems.append(f"no usable rate in {item.get('rates', item.get('rate_cents'))!r}")

    # Grounding check. The substantive question is whether this service exists in the
    # text the model was given, not whether it echoed the row character for character.
    # Requiring an exact echo tests formatting: an earlier version did, and rejected
    # every extraction from all four models over incidental whitespace.
    quote = str(item.get("source_quote") or "").strip()
    quote_matches = None
    if source_text:
        flat = _flatten(source_text)
        if name and _flatten(name) not in flat:
            problems.append(f"service {name!r} does not appear in the source text")
        if quote:
            quote_matches = _flatten(quote[:80]) in flat

    if problems:
        return None, problems

    record = {
        "service": name,
        "unit_basis": basis,
        "rates": rates,
        "rate_cents": rates[0]["cents"],
        "daily_cap": _as_int(item.get("daily_cap")),
        "nbd_uplift": _pct(item.get("nbd_uplift_pct")),
        "clause": item.get("clause"),
        "confidence": item.get("confidence"),
        "source_quote": quote,
        "quote_verbatim": quote_matches,
    }

    prem = item.get("threshold_premium") or None
    if isinstance(prem, dict):
        t, u = _as_int(prem.get("threshold")), _pct(prem.get("uplift_pct"))
        if t and u:
            record["threshold_premium"] = (t, u)

    discounts = []
    for d in item.get("volume_discounts") or []:
        if isinstance(d, dict):
            t, f = _as_int(d.get("threshold")), _pct(d.get("discount_pct"))
            if t and f:
                discounts.append((t, f))
    record["volume_discounts"] = sorted(discounts, key=lambda t: -t[0])

    bundle = item.get("bundle") or None
    if isinstance(bundle, dict):
        partner = str(bundle.get("partner_service") or "").strip()
        this_r = _as_int(bundle.get("this_rate_cents"))
        other_r = _as_int(bundle.get("partner_rate_cents"))
        if partner and this_r and other_r:
            record["bundle"] = (partner, this_r, other_r)

    return record, []


def build_spec(hospital, header, extracted, rejected=None):
    """Assemble validated records into the same shape `compile_contract` returns."""
    spec = new_spec(hospital, header["contract_number"],
                    header["effective_from"], header["effective_to"])
    spec["provenance"]["services"] = "extracted by model from prose clauses"

    for rec in extracted:
        name = rec["service"]
        # A service can appear in more than one chunk -- hospital 3 states seven of them
        # twice, once in the amendment with two dated rates and once in the base schedule
        # with one. Last-write-wins silently discarded the amendment, so the richer
        # reading is kept instead of whichever chunk happened to be processed last.
        existing = spec["services"].get(name)
        if existing and len(existing["rates"]) > len(rec["rates"]):
            continue
        spec["services"][name] = new_service(
            name, rec["unit_basis"],
            [new_rate(r["cents"], r["valid_from"], r["valid_to"]) for r in rec["rates"]],
            rec.get("daily_cap"))
        if rec.get("nbd_uplift") is not None:
            spec["nbd_uplifts"][name] = rec["nbd_uplift"]
        if rec.get("threshold_premium"):
            spec["threshold_premiums"][name] = rec["threshold_premium"]
        if rec.get("volume_discounts"):
            spec["volume_discounts"][name] = rec["volume_discounts"]

    # Bundles are stated from both sides, so the pair appears twice. Keep one copy,
    # and only where both services were actually extracted.
    seen = set()
    for rec in extracted:
        if not rec.get("bundle"):
            continue
        partner, this_rate, partner_rate = rec["bundle"]
        pair = tuple(sorted([rec["service"], partner]))
        if pair in seen:
            continue
        if partner not in spec["services"]:
            spec["warnings"].append(
                f"bundle on {rec['service']!r} names {partner!r}, which was not extracted")
            continue
        seen.add(pair)
        spec["bundles"].append((rec["service"], partner, this_rate, partner_rate))

    for reason in (rejected or []):
        spec["warnings"].append(reason)
    return spec


def extraction_frame(extracted):
    """The extraction as a table, for eyeballing and for the report."""
    import pandas as pd
    return pd.DataFrame([{
        "clause": r.get("clause"),
        "service": r["service"],
        "unit_basis": r["unit_basis"],
        "rate_cents": r["rate_cents"],
        "n_rates": len(r["rates"]),
        "daily_cap": r.get("daily_cap"),
        "nbd": str(r.get("nbd_uplift") or ""),
        "premium": str(r.get("threshold_premium") or ""),
        "discounts": str(r.get("volume_discounts") or ""),
        "bundle": (r.get("bundle") or ("",))[0],
        "confidence": r.get("confidence"),
        "quote_verbatim": r.get("quote_verbatim"),
    } for r in extracted])


# --------------------------------------------------------------------------
# Running an extraction over a whole contract
# --------------------------------------------------------------------------

def normalise_payload(payload):
    """Accept the shapes models actually return, and report which one arrived.

    The prompt asks for {"services": [...]}. Smaller models frequently return the bare
    array, and occasionally a single object. Rejecting those would measure instruction
    adherence rather than extraction quality, so the shape is normalised and the
    deviation recorded: envelope compliance is reported alongside accuracy rather than
    folded into it.
    """
    if isinstance(payload, list):
        return payload, "bare_list"
    if isinstance(payload, dict):
        if "services" in payload:
            return payload["services"], None
        for key in ("data", "items", "rows", "results"):
            if key in payload and isinstance(payload[key], list):
                return payload[key], f"key_{key}"
        if "service" in payload:
            return [payload], "single_object"
    return [], "unrecognised"


def extract_contract(model, prompt, chunks, header, hospital, verbose=True,
                     record=None):
    """Read every chunk with `model` and assemble one spec.

    One call per chunk, sequentially. There is no concurrency here on purpose: the
    whole job is thirteen calls, and asynchronous orchestration for thirteen calls is
    machinery with no beneficiary.

    Returns (spec, frame, telemetry). `record` is an optional dict that collects each
    raw reply, so a run can be committed and replayed by `StubModel` -- which is what
    makes the submission reproducible without a key.
    """
    extracted, rejected, telemetry = [], [], []

    for i, chunk in enumerate(chunks):
        reply, usage = model.generate(prompt, chunk["text"])
        if record is not None:
            record[str(i)] = {"reply": reply,
                              "usage": {k: v for k, v in usage.items() if k != "telemetry"}}

        payload, error = parse_json(reply)
        found, returned, deviation, unverified = 0, 0, None, 0
        if error:
            rejected.append(f"{chunk['title']}: {error}")
        else:
            items, deviation = normalise_payload(payload)
            returned = len(items)
            if deviation:
                rejected.append(f"{chunk['title']}: schema deviation ({deviation})")
            for item in items:
                if not isinstance(item, dict):
                    rejected.append(f"{chunk['title']}: non-object in services list")
                    continue
                rec, problems = validate_service(item, chunk["text"])
                if rec:
                    extracted.append(rec)
                    found += 1
                    if rec.get("quote_verbatim") is False:
                        unverified += 1
                else:
                    rejected.append(f"{chunk['title']} / {item.get('service', '?')}: "
                                    f"{'; '.join(problems)}")

        telemetry.append({
            "chunk": chunk["title"],
            "clauses_expected": chunk["n_clauses"],
            "services_returned": returned,
            "services_accepted": found,
            "parse_error": error,
            "schema_deviation": deviation,
            "quotes_unverified": unverified,
            "schema_enforced": usage.get("schema_enforced", False),
            **usage,
        })
        if verbose:
            flag = "!!" if (error or found != chunk["n_clauses"]) else "  "
            print(f" {flag} {chunk['title'][:46]:46s} "
                  f"expected {chunk['n_clauses']}  accepted {found}  "
                  f"{usage['input_tokens']:>5}in {usage['output_tokens']:>5}out "
                  f"{usage['seconds']:>6.1f}s")

    spec = build_spec(hospital, header, extracted, rejected)
    import pandas as pd
    return spec, extraction_frame(extracted), pd.DataFrame(telemetry)
