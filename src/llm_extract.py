"""Convert a model's JSON extraction into a contract spec.

Every field is validated on the way in and rejected rather than coerced. The prompt
requires a verbatim quote of the clause each rate came from; that quote is checked
against the source text, so a fabricated rule cannot pass.
"""

import re
from decimal import Decimal

from src.config import UNIT_BASIS
from src.contract_spec import new_spec, new_service, new_rate
from src.llm_client import parse_json

VALID_BASES = set(UNIT_BASIS.values())


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


def validate_service(item, source_text=None):
    """Check one extracted service. Returns (record, [reasons rejected])."""
    problems = []
    name = (item.get("service") or "").strip()
    if not name:
        return None, ["no service name"]

    basis = (item.get("unit_basis") or "").strip()
    if basis not in VALID_BASES:
        problems.append(f"unit_basis {basis!r} not one of {sorted(VALID_BASES)}")

    rate = _as_int(item.get("rate_cents"))
    if rate is None or rate <= 0:
        problems.append(f"rate_cents {item.get('rate_cents')!r} is not a positive integer")

    # A model that invents a supporting quote is caught here.
    quote = (item.get("source_quote") or "").strip()
    if source_text and quote:
        normalise = lambda s: re.sub(r"\s+", " ", s).strip()
        if normalise(quote[:80]) not in normalise(source_text):
            problems.append("source_quote does not appear in the article")

    if problems:
        return None, problems

    record = {
        "service": name,
        "unit_basis": basis,
        "rate_cents": rate,
        "daily_cap": _as_int(item.get("daily_cap")),
        "nbd_uplift": _pct(item.get("nbd_uplift_pct")),
        "clause": item.get("clause"),
        "confidence": item.get("confidence"),
        "source_quote": quote,
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
        partner = (bundle.get("partner_service") or "").strip()
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
        spec["services"][name] = new_service(name, rec["unit_basis"],
                                             [new_rate(rec["rate_cents"])],
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
        "daily_cap": r.get("daily_cap"),
        "nbd": str(r.get("nbd_uplift") or ""),
        "premium": str(r.get("threshold_premium") or ""),
        "discounts": str(r.get("volume_discounts") or ""),
        "bundle": (r.get("bundle") or ("",))[0],
        "confidence": r.get("confidence"),
    } for r in extracted])


# --------------------------------------------------------------------------
# Running an extraction over a whole contract
# --------------------------------------------------------------------------

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
            record[str(i)] = reply

        payload, error = parse_json(reply)
        found = 0
        if error:
            rejected.append(f"{chunk['title']}: {error}")
        else:
            for item in payload.get("services", []):
                rec, problems = validate_service(item, chunk["text"])
                if rec:
                    extracted.append(rec)
                    found += 1
                else:
                    rejected.append(f"{chunk['title']} / {item.get('service', '?')}: "
                                    f"{'; '.join(problems)}")

        telemetry.append({
            "chunk": chunk["title"],
            "clauses_expected": chunk["n_clauses"],
            "services_returned": 0 if error else len(payload.get("services", [])),
            "services_accepted": found,
            "parse_error": error,
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


def telemetry_summary(telemetry, model_name):
    """One row per model, for the comparison table."""
    return {
        "model": model_name,
        "calls": len(telemetry),
        "clauses_expected": int(telemetry.clauses_expected.sum()),
        "services_accepted": int(telemetry.services_accepted.sum()),
        "parse_failures": int(telemetry.parse_error.notna().sum()),
        "retries": int(telemetry.retries.sum()) if "retries" in telemetry else 0,
        "input_tokens": int(telemetry.input_tokens.sum()),
        "output_tokens": int(telemetry.output_tokens.sum()),
        "seconds": round(float(telemetry.seconds.sum()), 1),
    }
