"""Reprice a hospital's line items under its contract.

A single ordered pass. Cumulative volume discounts depend on utilisation prior to
each line, so invoices are not independent and cannot be parallelised. Per-patient
daily quantities, bundle co-occurrence and exclusion windows are precomputed.

Adjustment order, identical across all contracts: bundle substitution, facility
multiplier, plan-tier multiplier, premium or uplift, cumulative volume discount,
with half-up rounding after each step.
"""

import collections
from decimal import Decimal

import pandas as pd

from src.contracts import bundle_partner, rate_on
from src.money import apply, uplift, discount

ONE = Decimal(1)


def _attach_context(units, line_items, resolution):
    """Give every line item its service, patient, facility and plan tier."""
    li = line_items.copy()
    li["service"] = li["description"].map(
        dict(zip(resolution["description"], resolution["service"]))).astype(object)
    ctx = units.set_index("source_seq")[["patient_id", "facility_code", "plan_tier", "invoice_date"]]
    for col in ctx.columns:
        li[col] = li["source_seq"].map(ctx[col])
    return li


def _aggregates(li):
    """Everything the pricing pass needs to know before it starts."""
    daily_qty = collections.Counter()       # (patient, service, date) -> total units
    day_services = collections.defaultdict(set)   # (patient, date) -> services delivered
    service_dates = collections.defaultdict(list)  # (patient, service) -> dates
    for r in li.itertuples():
        if not isinstance(r.service, str) or pd.isna(r.service_date):
            continue
        key = (r.patient_id, r.service, r.service_date)
        daily_qty[key] += int(r.quantity)
        day_services[(r.patient_id, r.service_date)].add(r.service)
        service_dates[(r.patient_id, r.service)].append(r.service_date)
    return daily_qty, day_services, service_dates


def _exclusion_violations(spec, li):
    """Lines billed inside an exclusion window of the service that excludes them.

    "An exclusion window is measured in either direction from the Service Date
    of the Service which is excluded" (H1 s10.1), so the window is symmetric.
    """
    dates = collections.defaultdict(list)
    for r in li.itertuples():
        if isinstance(r.service, str) and not pd.isna(r.service_date):
            dates[(r.patient_id, r.service)].append(r.service_date)
    bad = set()
    for excluded, days, trigger in spec["exclusions"]:
        window = pd.Timedelta(days=days)
        for r in li.itertuples():
            if r.service != excluded or pd.isna(r.service_date):
                continue
            for other in dates.get((r.patient_id, trigger), ()):
                if abs(other - r.service_date) <= window:
                    bad.add(r.line_id)
                    break
    return bad


def _cross_invoice_duplicates(li):
    """Second and later billings of the same service, patient and service date.

    "The same Service may not be billed twice for the same Patient and the same
    Service Date, whether on one invoice or across several" (H1 s11.4). The
    first billing stands; later ones are not payable.
    """
    seen, dup = set(), set()
    for r in li.itertuples():                      # li is already in (date, line_id) order
        if not isinstance(r.service, str) or pd.isna(r.service_date):
            continue
        key = (r.patient_id, r.service, r.service_date)
        if key in seen:
            dup.add(r.line_id)
        else:
            seen.add(key)
    return dup


def reprice(spec, units, line_items, resolution):
    """Return the line items with the rate and total the contract requires.

    Adds:
        expected_unit_rate    the effective unit rate after every adjustment
        billable_quantity     quantity after applying any daily cap
        expected_line_total   expected_unit_rate x billable_quantity
        adjustments           which adjustments fired, for explanation
        alt_*                 counterfactual rates, so the classifier can say
                              *which* adjustment was mishandled rather than
                              falling back on a generic price mismatch
        disallowed            why a line is not payable at all, if it is not
    """
    li = _attach_context(units, line_items, resolution)
    daily_qty, day_services, service_dates = _aggregates(li)
    excluded = _exclusion_violations(spec, li)
    duplicated = _cross_invoice_duplicates(li)

    cumulative = collections.Counter()   # service -> units billed *before* this line
    day_used = collections.Counter()     # (patient, service, date) -> units already allowed

    out = []
    for r in li.itertuples():
        note, alt = [], {}
        svc = spec["services"].get(r.service) if isinstance(r.service, str) else None
        if svc is None:
            out.append({"rate": None, "billable": None, "total": None,
                        "note": "unknown_service", "alt": {}, "disallowed": None})
            continue

        rate = rate_on(svc, r.service_date.date() if not pd.isna(r.service_date) else None)
        if rate is None:
            out.append({"rate": None, "billable": None, "total": None,
                        "note": "no_rate_in_force", "alt": {}, "disallowed": None})
            continue

        # The whole adjustment chain, as a function of which facility and
        # plan-tier column is used. Evaluating it across the grid gives us the
        # rate this line would carry under every other column, with the same
        # premium and discount decisions applied — so a hospital that billed the
        # right service at the wrong column is identified as exactly that,
        # rather than disappearing into a generic price mismatch.
        partner, bundled_rate = bundle_partner(spec, r.service)
        bundled = bool(partner and partner in day_services.get((r.patient_id, r.service_date), ()))
        start_rate = bundled_rate if bundled else rate
        if bundled:
            note.append("bundle")

        facs = spec["facility_multipliers"].get(r.service, {})
        tiers = spec["tier_multipliers"].get(r.service, {})
        prem = spec["threshold_premiums"].get(r.service)
        nbd = spec["nbd_uplifts"].get(r.service)

        use_threshold = bool(prem) and daily_qty[(r.patient_id, r.service, r.service_date)] > prem[0]
        use_nbd = nbd is not None and not pd.isna(r.service_date) and r.service_date.weekday() >= 5
        use_discount = None
        for threshold, frac in spec["volume_discounts"].get(r.service, []):
            if cumulative[r.service] > threshold:
                use_discount = frac
                break                    # deepest threshold first; never compounded

        def chain(base, fv, tv, *, premium=True, discount_=True, bundle=True):
            """Price one line under a chosen set of readings, rounding at each step."""
            v = base if bundle else standalone_base
            if fv is not None:
                v = apply(v, fv)
            if tv is not None:
                v = apply(v, tv)
            if premium:
                if use_threshold:
                    v = uplift(v, prem[1])
                if use_nbd:
                    v = uplift(v, nbd)
            if discount_ and use_discount is not None:
                v = discount(v, use_discount)
            return v

        standalone_base = rate
        fv, tv = facs.get(r.facility_code), tiers.get(r.plan_tier)
        rate = chain(start_rate, fv, tv)

        if bundled:
            note.append("")                                  # keep note ordering stable
        if fv is not None:
            note.append(f"facility x{fv}")
        if tv is not None:
            note.append(f"tier x{tv}")
        if use_threshold:
            note.append(f"threshold +{prem[1]}")
        if use_nbd:
            note.append(f"non-business-day +{nbd}")
        if use_discount is not None:
            note.append(f"volume -{use_discount}")
        note = [n for n in note if n]

        # Counterfactuals: what the line would cost under each other reading.
        alt["standalone"] = chain(start_rate, fv, tv, bundle=False)
        alt["no_premium"] = chain(start_rate, fv, tv, premium=False)
        alt["no_discount"] = chain(start_rate, fv, tv, discount_=False)
        if prem and not use_threshold:
            alt["with_threshold"] = uplift(chain(start_rate, fv, tv, premium=False, discount_=False), prem[1])
        if nbd is not None and not use_nbd:
            alt["with_nbd"] = uplift(chain(start_rate, fv, tv, premium=False, discount_=False), nbd)
        if use_discount is None:
            for _, frac in spec["volume_discounts"].get(r.service, []):
                alt["with_discount"] = discount(chain(start_rate, fv, tv), frac)
                break
        if facs or tiers:
            alt["grid"] = {(fk, tk): chain(start_rate, facs.get(fk), tiers.get(tk))
                           for fk in (facs or {r.facility_code: None})
                           for tk in (tiers or {r.plan_tier: None})}
            alt["grid_cell"] = (r.facility_code, r.plan_tier)

        # Daily quantity cap: units beyond the cap are not billable.
        #
        # Trimmed to the contractual maximum. See decision log item 4.
        qty = int(r.quantity)
        billable = qty
        if svc["daily_cap"] is not None:
            key = (r.patient_id, r.service, r.service_date)
            remaining = max(0, svc["daily_cap"] - day_used[key])
            billable = min(qty, remaining)
            day_used[key] += billable
            if billable < qty:
                note.append(f"capped {qty}->{billable}")

        # Lines that are not payable at all.
        disallowed = None
        if r.line_id in duplicated:
            disallowed = "cross_invoice_duplicate"
        elif r.line_id in excluded:
            disallowed = "exclusion_window_violation"
        if disallowed:
            note.append(disallowed)

        cumulative[r.service] += qty
        total = 0 if disallowed else rate * billable
        out.append({"rate": rate, "billable": billable, "total": total,
                    "note": "; ".join(note), "alt": alt, "disallowed": disallowed})

    li["expected_unit_rate"] = [o["rate"] for o in out]
    li["billable_quantity"] = [o["billable"] for o in out]
    li["expected_line_total"] = [o["total"] for o in out]
    li["adjustments"] = [o["note"] for o in out]
    li["alternatives"] = [o["alt"] for o in out]
    li["disallowed"] = pd.Series([o["disallowed"] for o in out], index=li.index, dtype=object)
    return li


def quote(spec, service, quantity, service_date, facility_code=None, plan_tier=None,
          prior_units=0, with_partner=False):
    """Price one hypothetical line under the contract, showing every step.

    `quantity` is the patient's whole-day quantity of this service; `prior_units` is the
    cumulative utilisation before this line (0 means no volume discount can apply);
    `with_partner` says the bundle partner was delivered the same day. The assumptions
    are returned so the caller can print them beside the number.
    """
    svc = spec["services"][service]
    rate = rate_on(svc, service_date)
    if rate is None:
        raise ValueError(f"{service}: no rate in force on {service_date}")
    steps, assumptions = [], []

    partner, bundled_rate = bundle_partner(spec, service)
    value = rate
    if partner:
        if with_partner:
            value = bundled_rate
            steps.append(("bundled rate, partner delivered the same day", value))
        else:
            assumptions.append(f"bundle partner ({partner}) not delivered the same day")
            steps.append(("contracted rate", value))
    else:
        steps.append(("contracted rate", value))

    fv = spec["facility_multipliers"].get(service, {}).get(facility_code)
    if fv is not None:
        value = apply(value, fv); steps.append((f"x facility {facility_code} ({fv})", value))
    tv = spec["tier_multipliers"].get(service, {}).get(plan_tier)
    if tv is not None:
        value = apply(value, tv); steps.append((f"x plan tier {plan_tier} ({tv})", value))

    prem = spec["threshold_premiums"].get(service)
    if prem:
        if quantity > prem[0]:
            value = uplift(value, prem[1])
            steps.append((f"+{float(prem[1]) * 100:g}% premium: {quantity} units exceeds {prem[0]} "
                          f"in one Service Day, so the whole day is priced at the higher rate", value))
        else:
            assumptions.append(f"no premium: {quantity} does not exceed {prem[0]} units")
    nbd = spec["nbd_uplifts"].get(service)
    if nbd is not None:
        if service_date.weekday() >= 5:
            value = uplift(value, nbd)
            steps.append((f"+{float(nbd) * 100:g}% non-business-day uplift ({service_date:%A})", value))
        else:
            assumptions.append(f"no non-business-day uplift: {service_date:%A}")

    tiers = spec["volume_discounts"].get(service, [])
    applied = None
    for threshold, frac in tiers:
        if prior_units > threshold:
            applied = (threshold, frac)
            value = discount(value, frac)
            steps.append((f"-{float(frac) * 100:g}% volume discount: {prior_units} prior units exceeds {threshold}", value))
            break
    if tiers and applied is None:
        assumptions.append(f"no volume discount: prior utilisation {prior_units} does not exceed "
                           + " / ".join(str(t) for t, _ in sorted(tiers)))

    billable = quantity
    if svc["daily_cap"] is not None and quantity > svc["daily_cap"]:
        billable = svc["daily_cap"]
        steps.append((f"quantity capped at {billable} per Service Day", value))

    return {"service": service, "unit_basis": svc["unit_basis"], "quantity": quantity,
            "billable": billable, "unit_rate": value, "total": value * billable,
            "steps": steps, "assumptions": assumptions}
