"""Check a model's reading of hospital 2 against the contract text, rule by rule.

Hospital 2 has no regex compiler -- that is why it needs a model -- but its clauses
are templated closely enough that each rule family has one sentence shape. Reading
those shapes back with regex gives an independent answer to compare the model with.
This is a checker for the evaluation, not a substitute for the model: a sixth prose
contract with different wording would break these patterns and would still need the
model.

    python evaluation/verify_hospital_2.py                 # pinned model + prompt
    python evaluation/verify_hospital_2.py gpt-4o prose_v2
    python evaluation/verify_hospital_2.py deepseek prose_v1
"""

import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import audit, config

RATE = re.compile(r"^(\d+\.\d+) In respect of (.+?), the Provider shall invoice the Payer "
                  r"at the rate of GBP ([\d,]+\.\d{2}) per ([a-z ,]+?)[.,]")
CAP = re.compile(r"shall not bill more than [\w-]+ \((\d+)\)")
NBD = re.compile(r"does not fall on a Business Day, the rate applicable to it shall be "
                 r"increased by [\w-]+ percent \((\d+)%\)")
PREMIUM = re.compile(r"on a single Service Day exceeds [\w-]+ \((\d+)\)[^.]*?"
                     r"increased by [\w-]+ percent \((\d+)%\)")
DISCOUNT = re.compile(r"cumulative utilisation of this Service exceeds [\w\s-]*?\((\d+)\)"
                      r"[^.]*?discount of [\w\s-]*?\((\d+)%\)")
BUNDLE = re.compile(r"Where this Service and (.+?) are both delivered[^.]*?this Service at "
                    r"GBP ([\d,]+\.\d{2})[^.]*?and .+? at GBP ([\d,]+\.\d{2})")


def cents(text):
    return int(round(float(text.replace(",", "")) * 100))


def pct(text):
    return Decimal(text) / 100


def rules_from_text(path):
    """{service: rules} read directly from the contract's sentence shapes."""
    truth = {}
    for line in open(path).read().splitlines():
        m = RATE.match(line.strip())
        if not m:
            continue
        clause, name, rate, _ = m.groups()
        cap, nbd, prem, bundle = CAP.search(line), NBD.search(line), PREMIUM.search(line), BUNDLE.search(line)
        truth[name] = {
            "clause": clause,
            "rate": cents(rate),
            "cap": int(cap.group(1)) if cap else None,
            "nbd": pct(nbd.group(1)) if nbd else None,
            "premium": (int(prem.group(1)), pct(prem.group(2))) if prem else None,
            "discounts": sorted(((int(a), pct(b)) for a, b in DISCOUNT.findall(line)),
                                key=lambda t: -t[0]),
            "bundle": bundle.group(1) if bundle else None,
        }
    return truth


def rules_from_spec(spec, name):
    svc = spec["services"][name]
    partner = next((b for a, b, *_ in spec["bundles"] if a == name),
                   next((a for a, b, *_ in spec["bundles"] if b == name), None))
    return {"rate": svc["rates"][0]["cents"], "cap": svc["daily_cap"],
            "nbd": spec["nbd_uplifts"].get(name),
            "premium": spec["threshold_premiums"].get(name),
            "discounts": spec["volume_discounts"].get(name, []),
            "bundle": partner}


def verify(spec, contract_path, show=True):
    truth = rules_from_text(contract_path)
    defects = []
    for name, want in truth.items():
        if name not in spec["services"]:
            defects.append(("MISSED", "service", want["clause"], name, None, None))
            continue
        got = rules_from_spec(spec, name)
        for field in ("rate", "cap", "nbd", "premium", "discounts", "bundle"):
            if got[field] != want[field]:
                kind = ("INVENTED" if want[field] in (None, []) else
                        "MISSED" if got[field] in (None, []) else "WRONG")
                defects.append((kind, field, want["clause"], name, want[field], got[field]))
    for name in set(spec["services"]) - set(truth):
        defects.append(("HALLUCINATED", "service", "", name, None, None))

    if show:
        for kind, field, clause, name, want, got in defects:
            print(f"  {kind:12} {field:9} {clause:5} {name[:46]:46} contract={want}  model={got}")
        exact_rates = sum(spec["services"][n]["rates"][0]["cents"] == t["rate"]
                          for n, t in truth.items() if n in spec["services"])
        print(f"  {len(defects)} defects over {len(truth)} services; "
              f"rates exact {exact_rates}/{len(truth)}")
    return defects, len(truth)


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else config.EXTRACTION_MODEL
    version = sys.argv[2] if len(sys.argv) > 2 else config.PROSE_PROMPT_VERSION
    spec = audit.load_spec(str(config.DATA), "hospital_2", model_name=model, prompt_version=version)
    print(f"{model} / {version}  ({'replayed' if spec['provenance']['replayed'] else 'live'})")
    defects, _ = verify(spec, config.CONTRACTS / "hospital_2" / "master_services_agreement.md")
    sys.exit(1 if defects else 0)
