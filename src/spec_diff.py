"""Score one contract reading against another.

The tabular contracts yield a known-correct spec, so a model given the same text can
be marked field by field at no labelling cost. Missed, wrong and hallucinated rules
are counted separately; money is compared exactly.
"""

import pandas as pd

RULE_FAMILIES = ["threshold_premiums", "nbd_uplifts", "volume_discounts",
                 "bundles", "exclusions", "facility_multipliers", "tier_multipliers"]


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def _rule_items(spec, family):
    """A rule family flattened to a comparable set of tuples."""
    value = spec.get(family)
    if family in ("bundles", "exclusions"):
        return {tuple(t) for t in value}
    if family in ("facility_multipliers", "tier_multipliers"):
        return {(name, k, str(v)) for name, cols in value.items() for k, v in cols.items()}
    if family == "volume_discounts":
        return {(name, t, str(f)) for name, tiers in value.items() for t, f in tiers}
    if family == "threshold_premiums":
        return {(name, t, str(f)) for name, (t, f) in value.items()}
    return {(name, str(f)) for name, f in value.items()}          # nbd_uplifts


def compare_specs(gold, pred):
    """Score one spec against another. Returns a flat dict of metrics."""
    g_names, p_names = set(gold["services"]), set(pred["services"])
    shared = g_names & p_names
    s_p, s_r, s_f = _prf(len(shared), len(p_names - g_names), len(g_names - p_names))

    rate_ok = basis_ok = cap_ok = 0
    for name in shared:
        g, p = gold["services"][name], pred["services"][name]
        if sorted((r["cents"], r["valid_from"], r["valid_to"]) for r in g["rates"]) == \
           sorted((r["cents"], r["valid_from"], r["valid_to"]) for r in p["rates"]):
            rate_ok += 1
        if g["unit_basis"] == p["unit_basis"]:
            basis_ok += 1
        if g["daily_cap"] == p["daily_cap"]:
            cap_ok += 1

    out = {
        "gold_services": len(g_names),
        "found_services": len(shared),
        "missed_services": len(g_names - p_names),
        "hallucinated_services": len(p_names - g_names),
        "service_precision": s_p, "service_recall": s_r, "service_f1": s_f,
        "rate_exact": round(rate_ok / len(shared), 4) if shared else 0.0,
        "unit_basis_exact": round(basis_ok / len(shared), 4) if shared else 0.0,
        "daily_cap_exact": round(cap_ok / len(shared), 4) if shared else 0.0,
    }

    hallucinated_rules = 0
    for family in RULE_FAMILIES:
        g_items, p_items = _rule_items(gold, family), _rule_items(pred, family)
        tp = len(g_items & p_items)
        fp = len(p_items - g_items)
        fn = len(g_items - p_items)
        hallucinated_rules += fp
        p_, r_, f_ = _prf(tp, fp, fn)
        out[f"{family}_f1"] = f_
        out[f"{family}_support"] = len(g_items)

    out["hallucinated_rules"] = hallucinated_rules
    out["hallucination_rate"] = round(
        (out["hallucinated_services"] + hallucinated_rules)
        / max(1, len(g_names) + sum(len(_rule_items(gold, f)) for f in RULE_FAMILIES)), 4)
    return out


def diff_report(gold, pred, limit=10):
    """Human-readable list of what differs, for error analysis."""
    rows = []
    g_names, p_names = set(gold["services"]), set(pred["services"])
    for name in sorted(g_names - p_names)[:limit]:
        rows.append({"kind": "missed_service", "item": name, "gold": "", "predicted": ""})
    for name in sorted(p_names - g_names)[:limit]:
        rows.append({"kind": "HALLUCINATED_service", "item": name, "gold": "", "predicted": ""})
    for name in sorted(g_names & p_names):
        g, p = gold["services"][name], pred["services"][name]
        gr = sorted(r["cents"] for r in g["rates"])
        pr = sorted(r["cents"] for r in p["rates"])
        if gr != pr:
            rows.append({"kind": "wrong_rate", "item": name, "gold": gr, "predicted": pr})
        if g["unit_basis"] != p["unit_basis"]:
            rows.append({"kind": "wrong_unit_basis", "item": name,
                         "gold": g["unit_basis"], "predicted": p["unit_basis"]})
        if g["daily_cap"] != p["daily_cap"]:
            rows.append({"kind": "wrong_daily_cap", "item": name,
                         "gold": g["daily_cap"], "predicted": p["daily_cap"]})
    for family in RULE_FAMILIES:
        g_items, p_items = _rule_items(gold, family), _rule_items(pred, family)
        for item in sorted(g_items - p_items, key=str)[:limit]:
            rows.append({"kind": f"missed_{family}", "item": str(item), "gold": "", "predicted": ""})
        for item in sorted(p_items - g_items, key=str)[:limit]:
            rows.append({"kind": f"HALLUCINATED_{family}", "item": str(item),
                         "gold": "", "predicted": ""})
    return pd.DataFrame(rows, columns=["kind", "item", "gold", "predicted"])
