"""Matches a messy invoice description to a contracted service. Done by price, not by
text: a contract can only produce a small set of unit prices, so a description's usual
price identifies its service. Text similarity only breaks the rare ties.
"""

import collections
from decimal import Decimal

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.contracts import bundle_partner
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
    can fail silently. See the decision log.
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


# Thresholds for treating a price match as coincidental rather than an alias.
# Calibrated on hospital 1; the margin is reported per hospital.
UNKNOWN_MAX_LEXICAL = 0.20
UNKNOWN_MAX_ROWS = 2

# Where a price matches more than one service, text decides -- but how decisively it
# decided is itself information. A tie won by a wide margin is near-certain; one won by
# a hair is a coin-flip, and reporting both at the same confidence is the failure the
# task singles out. Confidence follows the margin, and below DECIDED_MIN the
# description is reported as ambiguous rather than resolved, with both candidates named.
DECISIVE_MARGIN = 0.30
DECIDED_MIN = 0.10


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
        margin, runner_up = None, None

        if len(candidates) == 1:
            service = next(iter(candidates))
            agrees = service == lex_best
            method, conf = "price_unique", (0.98 if agrees else 0.90)
        elif len(candidates) > 1:
            among = lex.rank(desc, among=candidates)
            service, top_score = among[0]
            runner_up, second_score = among[1] if len(among) > 1 else (None, 0.0)
            margin = top_score - second_score
            agrees = True
            if margin >= DECISIVE_MARGIN:
                method, conf = "price_tiebreak_text", 0.90
            elif margin >= DECIDED_MIN:
                method, conf = "price_tiebreak_narrow", 0.70
            else:
                # Neither signal separates the candidates. Naming one would be a guess
                # presented as a finding; the pair is surfaced for review instead.
                method, conf = "ambiguous", 0.40
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
            "tiebreak_margin": round(margin, 3) if len(candidates) > 1 else None,
            "runner_up": runner_up if len(candidates) > 1 else None,
            "n_candidates": len(candidates), "modal_basis": mode[0], "modal_price": mode[1],
            "modal_share": round(mode_n / total, 3), "n_rows": total,
            "lexical_best": lex_best, "lexical_score": round(float(lex_score), 3),
            "score_of_chosen": round(chosen_score, 3),
            "signals_agree": agrees, "confidence": conf,
        })
    return pd.DataFrame(rows).sort_values(["method", "description"]).reset_index(drop=True)
