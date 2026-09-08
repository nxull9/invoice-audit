"""Repricing a hospital's line items under its contract.

This is the financial source of truth. No model touches it: given a
`ContractSpec` and a description->service resolution, it computes what each
line item *should* have cost, and the caller compares that with what was
billed.

Two structural facts shape the implementation.

**It is one ordered pass, not a per-invoice loop.** Cumulative volume discounts
are counted "cumulatively across the whole term of this Agreement and
aggregated across all Patients" in service-date order, ties broken by line
identifier (H1 s7.1-7.2, H5 s8.1). You cannot price invoice 47 without having
priced 1-46 first, so invoices are *not* independent and cannot be parallelised.

**Some rules need the whole table before pricing starts.** A threshold premium
is assessed against the aggregate quantity delivered to a patient on a service
day "across all line items and all invoices" (H5 s5.1); a bundled rate applies
only if both services reached the patient on the same day; an exclusion window
looks in both directions from a service date. So a set of aggregates is built
in a first pass, and the second pass prices in order.

The adjustment order is stated identically in H1 s3.2, H2 s3.2 and H5 s3.1:
bundle substitution, facility multiplier, plan-tier multiplier, premium or
uplift, cumulative volume discount — rounding half-up after each step.
"""

import collections
from decimal import Decimal

import pandas as pd

from src.money import apply, uplift, discount

ONE = Decimal(1)


def _attach_context(units, line_items, resolution):
    """Give every line item its service, patient, facility and plan tier."""
    li = line_items.copy()
    li["service"] = li["description"].map(dict(zip(resolution["description"], resolution["service"])))
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
        if r.service is None or pd.isna(r.service_date):
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
        if r.service and not pd.isna(r.service_date):
            dates[(r.patient_id, r.service)].append(r.service_date)
    bad = set()
    for excluded, days, trigger in spec.exclusions:
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
        if not r.service or pd.isna(r.service_date):
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
        svc = spec.services.get(r.service) if r.service else None
        if svc is None:
            out.append({"rate": None, "billable": None, "total": None,
                        "note": "unknown_service", "alt": {}, "disallowed": None})
            continue

        rate = svc.rate_on(r.service_date.date() if not pd.isna(r.service_date) else None)
        if rate is None:
            out.append({"rate": None, "billable": None, "total": None,
                        "note": "no_rate_in_force", "alt": {}, "disallowed": None})
            continue

        standalone = rate

        # (a) bundled rate substitution
        partner, bundled_rate = spec.bundle_partner(r.service)
        if partner and partner in day_services.get((r.patient_id, r.service_date), ()):
            rate = bundled_rate
            note.append("bundle")
        alt["standalone"] = standalone

        # (b) facility multiplier, (c) plan-tier multiplier
        for kind, table, key in (("facility", spec.facility_multipliers, r.facility_code),
                                 ("tier", spec.tier_multipliers, r.plan_tier)):
            m = table.get(r.service, {}).get(key)
            if m is not None:
                rate = apply(rate, m)
                alt["standalone"] = apply(alt["standalone"], m)
                note.append(f"{kind} x{m}")

        alt["no_premium"] = rate

        # (d) premium or uplift
        prem = spec.threshold_premiums.get(r.service)
        if prem:
            alt["with_threshold"] = uplift(rate, prem[1])
            if daily_qty[(r.patient_id, r.service, r.service_date)] > prem[0]:
                rate = alt["with_threshold"]; note.append(f"threshold +{prem[1]}")
        nbd = spec.nbd_uplifts.get(r.service)
        if nbd is not None:
            alt["with_nbd"] = uplift(rate, nbd)
            if not pd.isna(r.service_date) and r.service_date.weekday() >= 5:
                rate = alt["with_nbd"]; note.append(f"non-business-day +{nbd}")

        alt["no_discount"] = rate

        # (e) cumulative volume discount, on utilisation *prior to* this line
        discounts = spec.volume_discounts.get(r.service, [])
        for threshold, frac in discounts:
            alt.setdefault("with_discount", discount(rate, frac))
            if cumulative[r.service] > threshold:
                rate = discount(rate, frac); note.append(f"volume -{frac}")
                break                        # deepest threshold first; never compounded

        # Daily quantity cap: units beyond the cap are not billable.
        #
        # KNOWN LIMITATION, measured on hospital 1. We trim to the cap, which is
        # what the contract entitles the provider to ("Maximum billable units
        # per Patient per Service Day"). The labels instead restore the original
        # pre-inflation quantity: on the four capped invoices they imply
        # quantities of 3, 9, 3 and 3 against caps of 4, 12, 12 and 8, with no
        # co-occurring line item to explain the remainder. That original
        # quantity is not recoverable from the contract, so we do not try to
        # guess it. All four invoices are still flagged correctly; only their
        # expected_total is affected, and always in the conservative direction
        # (we allow the provider the contractual maximum). Confidence on
        # expected_total is reduced for these lines accordingly.
        qty = int(r.quantity)
        billable = qty
        if svc.daily_cap is not None:
            key = (r.patient_id, r.service, r.service_date)
            remaining = max(0, svc.daily_cap - day_used[key])
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
    li["disallowed"] = [o["disallowed"] for o in out]
    return li
