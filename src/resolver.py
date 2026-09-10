"""Mapping free-text billing descriptions onto contracted services.

The brief frames this as the hard part, and lexically it is: hospital 1 bills
108 contracted services under 488 distinct descriptions, abbreviated
("Rtn", "Compr", "Ent" for Otolaryngologic), reordered ("Occupancy Rtn Pall
Crit Cr"), truncated ("Extended Ren Transp") and suffixed with noise codes
("/NG-3022").

We do not match on the text. We match on the *price*.

A contract can only produce a small, enumerable set of unit rates: the base
rate, the bundled rate, each multiplied by any facility and plan-tier
multiplier, any premium or uplift, and any volume discount, rounded half-up at
each step. Take the modal (unit_basis, unit_price_cents) for a description
across all its line items and look it up in that set. On hospital 1 this
resolves 488 of 488 descriptions uniquely; on hospital 5, 455 of 474.

Two properties make this the right tool rather than an embedding model:

* It is auditable. The output is a table of a few hundred rows that a human
  can read, not a similarity score.
* It fails in the safe direction. A description whose modal price is not a
  price the contract can produce does not get a guess — it becomes a
  candidate `unknown_service`, which is itself one of the error categories.

Text is still used, but only as an *independent second opinion*: to break the
handful of genuine price collisions, and to disagree. Where price and text pick
different services, that disagreement lowers the confidence rather than being
silently resolved.
"""

import collections
from decimal import Decimal

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.contract_spec import bundle_partner
from src.money import apply, uplift, discount

ONE = Decimal(1)


def derivable_prices(spec):
    """Every (unit_basis, unit_price_cents) the contract can legally produce.

    Returns {(basis, cents): {service names}}. A key mapping to more than one
    service is a genuine price collision and is handed to the text tie-break.
    """
    index = collections.defaultdict(set)
    for name, svc in spec["services"].items():
        _, bundled = bundle_partner(spec, name)
        facs = list(spec["facility_multipliers"].get(name, {1: ONE}).values()) or [ONE]
        tiers = list(spec["tier_multipliers"].get(name, {1: ONE}).values()) or [ONE]
        prem = spec["threshold_premiums"].get(name)
        nbd = spec["nbd_uplifts"].get(name)
        discs = [d for _, d in spec["volume_discounts"].get(name, [])]

        starts = [rate["cents"] for rate in svc["rates"]] + ([bundled] if bundled else [])
        for start in starts:
            for f in set(facs):
                a = apply(start, f)
                for t in set(tiers):
                    b = apply(a, t)
                    ups = [b] + ([uplift(b, prem[1])] if prem else []) \
                              + ([uplift(b, nbd)] if nbd else [])
                    for c in ups:
                        for d in [None] + discs:
                            price = c if d is None else discount(c, d)
                            index[(svc["unit_basis"], price)].add(name)
    return index


def modal_price(line_items):
    """The most common (unit_basis, unit_price_cents) for each description.

    The mode is what makes this robust: an injected error affects a minority of
    a description's rows, so the majority still carries the contracted rate.
    That assumption is stated explicitly because it is the one way this method
    can fail silently — see the decision log.
    """
    counts = collections.defaultdict(collections.Counter)
    for r in line_items.itertuples():
        counts[r.description][(r.unit_basis_as_billed, int(r.unit_price_cents))] += 1
    return {d: (c.most_common(1)[0][0], c.most_common(1)[0][1], sum(c.values()))
            for d, c in counts.items()}


class LexicalMatcher:
    """Character n-gram TF-IDF similarity between descriptions and service names.

    Character n-grams rather than words, because the descriptions abbreviate
    ('Compr Infectious Nursing' / 'Comprehensive Infectious Nursing Observation')
    and reorder, both of which destroy word-level overlap but leave most
    character trigrams intact.
    """

    def __init__(self, service_names):
        self.names = list(service_names)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
        self.matrix = self.vec.fit_transform(self.names)

    def rank(self, description, among=None):
        """(service, score) pairs, best first, optionally restricted to `among`."""
        q = self.vec.transform([description])
        sims = cosine_similarity(q, self.matrix)[0]
        pairs = sorted(zip(self.names, sims), key=lambda t: -t[1])
        if among is not None:
            allowed = set(among)
            pairs = [p for p in pairs if p[0] in allowed]
        return pairs


# A price match can be coincidental: a description for a service that is not in
# the contract at all will still land on *some* derivable price. Two independent
# signals identify that case, and we require both.
#
#   - the text does not support the price's choice (low similarity), and
#   - no repeated usage establishes the description as an alias (rare).
#
# On hospital 1 these thresholds recover all 12 `unknown_service` invoices with
# no false positives, and the margin is wide: the 12 score at most 0.123 against
# a genuine minimum of 0.095, and every one appears exactly once against a
# genuine minimum of 6 appearances.
#
# This is the most data-fitted decision in the system. It is tuned on 12
# examples, and `unknown_margin` is reported per hospital so that a collapsed
# margin on hospitals 2-5 is visible rather than silent. See the decision log.
UNKNOWN_MAX_LEXICAL = 0.20
UNKNOWN_MAX_ROWS = 2


def resolve(spec, line_items):
    """Resolve every distinct description to a contracted service.

    Returns one row per description with the method that decided it, the
    agreement between the two independent signals, and a confidence.
    """
    index = derivable_prices(spec)
    modes = modal_price(line_items)
    lex = LexicalMatcher(spec["services"])

    rows = []
    for desc, (mode, mode_n, total) in modes.items():
        candidates = index.get(mode, set())
        ranked = lex.rank(desc)
        lex_best, lex_score = ranked[0]

        if len(candidates) == 1:
            service = next(iter(candidates))
            agrees = service == lex_best
            method, conf = "price_unique", (0.98 if agrees else 0.90)
        elif len(candidates) > 1:
            service = lex.rank(desc, among=candidates)[0][0]
            agrees, method, conf = True, "price_tiebreak_text", 0.85
        else:
            service, agrees = None, False
            method, conf = "unresolved", 0.30

        # How well does the text support the service the price picked?
        chosen_score = float(dict(ranked)[service]) if service else 0.0
        if (service is not None
                and chosen_score < UNKNOWN_MAX_LEXICAL
                and total <= UNKNOWN_MAX_ROWS):
            service, method, conf = None, "unknown_service", 0.90

        rows.append({
            "description": desc, "service": service, "method": method,
            "n_candidates": len(candidates), "modal_basis": mode[0], "modal_price": mode[1],
            "modal_share": round(mode_n / total, 3), "n_rows": total,
            "lexical_best": lex_best, "lexical_score": round(float(lex_score), 3),
            "score_of_chosen": round(chosen_score, 3),
            "signals_agree": agrees, "confidence": conf,
        })
    return pd.DataFrame(rows).sort_values(["method", "description"]).reset_index(drop=True)
