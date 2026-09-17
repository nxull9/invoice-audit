"""Is the line reproduction rate circular?

Services are matched to descriptions by price, and then I report how many lines the
engine reprices to the billed amount. A reviewer asked whether that number is
guaranteed by the matching method rather than earned. Three measurements, no argument:

1. Split the lines into the ones the match makes trivial and the ones it does not. A
   line whose expected unit price equals the modal price that chose its service proves
   little. The measured set is the lines whose expected unit price differs from it,
   because the engine applied a bundle, a facility or tier multiplier, a premium, a
   weekend uplift or a volume discount. A daily cap is deliberately not in that list: it
   changes the billable quantity, not the unit price.
2. Hold out half the invoices. Fit the description-to-service mapping on the other half
   only, then measure reproduction on the held-out half, whose prices never influenced
   the mapping.
3. Throw the price away. Match every description by text similarity alone, then measure
   how often that agrees with the price-based match, and what reproduction looks like.

    python evaluation/resolution_holdout.py [hospital ...]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src import audit, config, resolver
from src.data import build_invoice_units, load_invoices, load_line_items
from src.pricing import reprice


def reproduction(priced, mask=None):
    """Share of line items whose expected total equals the billed total."""
    rows = priced if mask is None else priced[mask]
    if not len(rows):
        return float("nan"), 0
    return float((rows.expected_line_total == rows.line_total_cents).mean()), len(rows)


def split_by_match(result):
    """Reproduction on the lines the match makes trivial, and on the ones it does not."""
    priced, res = result["priced"], result["resolution"]
    modal = dict(zip(res.description, res.modal_price))
    expected_is_modal = priced.apply(
        lambda r: pd.notna(r.expected_unit_rate) and modal.get(r.description) == r.expected_unit_rate,
        axis=1)
    trivial, n_trivial = reproduction(priced, expected_is_modal)
    tested, n_tested = reproduction(priced, ~expected_is_modal)
    overall, n_all = reproduction(priced)
    return {"hospital": result["hospital"], "lines": n_all, "overall": overall,
            "at_modal_rate": n_trivial, "at_modal_reproduced": trivial,
            "adjusted_away": n_tested, "adjusted_reproduced": tested}


def holdout(data_root, hospital, spec, seed=0):
    """Fit the mapping on half the invoices, measure reproduction on the other half."""
    invoices = load_invoices(data_root, hospital)
    lines = load_line_items(data_root, hospital)
    units = build_invoice_units(invoices, lines)

    keys = pd.Series(sorted(lines.source_seq.unique()))
    fit_keys = set(keys.sample(frac=0.5, random_state=seed))
    fit_lines = lines[lines.source_seq.isin(fit_keys)]
    test_mask = ~lines.source_seq.isin(fit_keys)

    fitted = resolver.resolve(spec, fit_lines)              # prices of held-out lines never seen
    priced = reprice(spec, units, lines, fitted)
    rate, n = reproduction(priced, test_mask)

    seen = set(fitted.description)
    unseen = sorted(set(lines[test_mask].description) - seen)
    unseen_lines = int(test_mask.sum() - lines[test_mask].description.isin(seen).sum())
    return {"hospital": hospital, "held_out_lines": n, "reproduced": rate,
            "descriptions_unseen_in_fit_half": len(unseen), "lines_from_unseen": unseen_lines}


def price_blind(data_root, hospital, spec):
    """Match every description by text alone, then compare with the price-based match."""
    invoices = load_invoices(data_root, hospital)
    lines = load_line_items(data_root, hospital)
    units = build_invoice_units(invoices, lines)

    by_price = resolver.resolve(spec, lines)
    matcher = resolver.LexicalMatcher(spec["services"])
    rows = []
    for description in by_price.description:
        service, score = matcher.rank(description)[0]
        rows.append({"description": description, "service": service, "method": "text_only",
                     "confidence": round(float(score), 3)})
    by_text = pd.DataFrame(rows)

    agree = (by_price.set_index("description").service
             == by_text.set_index("description").service).mean()
    priced = reprice(spec, units, lines, by_text)
    rate, n = reproduction(priced)
    return {"hospital": hospital, "descriptions": len(by_text),
            "text_agrees_with_price": float(agree), "reproduced_text_only": rate, "lines": n}


def run(hospitals=None):
    data_root = str(config.DATA)
    hospitals = hospitals or config.HOSPITALS
    decomposed, held, blind = [], [], []
    for hospital in hospitals:
        result = audit.audit_hospital(data_root, hospital)
        decomposed.append(split_by_match(result))
        held.append(holdout(data_root, hospital, result["spec"]))
        blind.append(price_blind(data_root, hospital, result["spec"]))

    pct = lambda s: (s * 100).round(2)
    d = pd.DataFrame(decomposed)
    d["overall"], d["at_modal_reproduced"], d["adjusted_reproduced"] = (
        pct(d.overall), pct(d.at_modal_reproduced), pct(d.adjusted_reproduced))
    print("1. reproduction split by whether the match already fixed the rate\n")
    print(d.to_string(index=False))
    print("\n   'adjusted_away' = expected unit price differs from the modal price that\n"
          "   chose the service: a bundle, multiplier, premium, uplift or discount moved it.\n"
          "   A daily cap is not counted here; it changes quantity, not the unit price.\n")

    h = pd.DataFrame(held); h["reproduced"] = pct(h.reproduced)
    print("\n2. mapping fitted on half the invoices, measured on the held-out half\n")
    print(h.to_string(index=False))

    b = pd.DataFrame(blind)
    b["text_agrees_with_price"], b["reproduced_text_only"] = (
        pct(b.text_agrees_with_price), pct(b.reproduced_text_only))
    print("\n\n3. matching by text only, price ignored\n")
    print(b.to_string(index=False))
    return d, h, b


if __name__ == "__main__":
    run(sys.argv[1:] or None)
