"""The contract representation every compiler produces.

Plain dicts, so a spec is printable, comparable and JSON-serialisable — required for
diffing a model's extraction against a regex-built one.
"""


def new_rate(cents, valid_from=None, valid_to=None):
    """A rate, optionally bounded in time.

    Hospital 3's Amendment No. 1 substitutes rates from 1 January 2025 *by service
    date*, so one service can hold several non-overlapping rates.
    """
    return {"cents": int(cents), "valid_from": valid_from, "valid_to": valid_to}


def rate_covers(rate, on):
    """Is this rate in force on the given date?"""
    if on is None:
        return rate["valid_from"] is None and rate["valid_to"] is None
    return ((rate["valid_from"] is None or on >= rate["valid_from"])
            and (rate["valid_to"] is None or on <= rate["valid_to"]))


def rate_on(service, service_date):
    """The contracted rate in force for a service on a date, or None."""
    for rate in service["rates"]:
        if rate_covers(rate, service_date):
            return rate["cents"]
    # A rate with no date bounds always applies; fall back to it.
    for rate in service["rates"]:
        if rate["valid_from"] is None and rate["valid_to"] is None:
            return rate["cents"]
    return None


def new_service(name, unit_basis, rates, daily_cap=None):
    return {"name": name, "unit_basis": unit_basis, "rates": rates, "daily_cap": daily_cap}


def new_spec(hospital, contract_number, effective_from, effective_to):
    """An empty contract spec, ready for a compiler to fill."""
    return {
        "hospital": hospital,
        "contract_number": contract_number,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "services": {},               # name -> service dict
        "threshold_premiums": {},     # name -> (threshold_qty, uplift_fraction)
        "nbd_uplifts": {},            # name -> uplift_fraction
        "volume_discounts": {},       # name -> [(threshold, fraction), ...] deepest first
        "bundles": [],                # [(service_a, service_b, rate_a, rate_b), ...]
        "exclusions": [],             # [(service, days, other_service), ...]
        "facility_multipliers": {},   # name -> {facility_code: multiplier}
        "tier_multipliers": {},       # name -> {plan_tier: multiplier}
        "provenance": {},             # rule family -> where it came from
        "warnings": [],               # anything we could not read cleanly
    }


def bundle_partner(spec, service):
    """The service that must co-occur for a bundled rate, and the substituted rate."""
    for a, b, rate_a, rate_b in spec["bundles"]:
        if service == a:
            return b, rate_a
        if service == b:
            return a, rate_b
    return None, None


def summarise(spec):
    """One row describing a compiled spec, for eyeballing that it read correctly."""
    return {
        "hospital": spec["hospital"],
        "contract": spec["contract_number"],
        "services": len(spec["services"]),
        "priced_periods": sum(len(s["rates"]) for s in spec["services"].values()),
        "daily_caps": sum(s["daily_cap"] is not None for s in spec["services"].values()),
        "threshold_premiums": len(spec["threshold_premiums"]),
        "nbd_uplifts": len(spec["nbd_uplifts"]),
        "volume_discounts": len(spec["volume_discounts"]),
        "bundles": len(spec["bundles"]),
        "exclusions": len(spec["exclusions"]),
        "facility_multipliers": len(spec["facility_multipliers"]),
        "tier_multipliers": len(spec["tier_multipliers"]),
        "warnings": len(spec["warnings"]),
    }
