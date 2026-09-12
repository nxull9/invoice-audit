"""Reads the four table contracts (hospitals 1, 3, 4, 5) into a spec with regex. One
function per hospital. A rule that names a service missing from the rate table
becomes a warning, never a silent drop.
"""

from datetime import date

from src.config import UNIT_BASIS
from src.contracts import read_header
from src.contracts import new_spec, new_service, new_rate
from src.markdown_tables import (sections, table, find, columns, cents, fraction,
                                 quantity, decimal_val)


def _check_known(spec, names, where):
    """Record any service named by a rule table that the rate schedule lacks."""
    for n in names:
        if n not in spec["services"]:
            spec["warnings"].append(f"{where}: unknown service {n!r} not in rate schedule")


def _read_rule_tables(spec, secs, *, premiums, nbd, discounts, bundles, exclusions,
                      caps=None):
    """The rule families every contract states, in whatever section it states them.

    Columns are matched by header text rather than by position: hospital 1's bundle
    table is `Service A | Service B | Rate A | Rate B` while hospital 5's is
    `Service A | Rate A | Service B | Rate B`. Reading by position would silently swap
    a service name for a price.
    """
    body = find(secs, *premiums)
    if body:
        rows, hdr = table(body)
        for name, threshold, uplift in columns(rows, hdr, "Service", "threshold|exceeds", "Uplift"):
            spec["threshold_premiums"][name] = (quantity(threshold), fraction(uplift))

    body = find(secs, *nbd)
    if body:
        rows, hdr = table(body)
        if rows:
            for name, uplift in columns(rows, hdr, "Service", "Uplift"):
                spec["nbd_uplifts"][name] = fraction(uplift)

    body = find(secs, *discounts)
    if body:
        rows, hdr = table(body)
        for name, threshold, disc in columns(rows, hdr, "Service", "utilisation|exceeds", "Discount"):
            spec["volume_discounts"].setdefault(name, []).append((quantity(threshold), fraction(disc)))
        for name in spec["volume_discounts"]:
            spec["volume_discounts"][name].sort(key=lambda t: -t[0])

    body = find(secs, *bundles)
    if body:
        rows, hdr = table(body)
        for a, b, ra, rb in columns(rows, hdr, "Service A", "Service B", "rate A", "rate B"):
            spec["bundles"].append((a, b, cents(ra), cents(rb)))

    body = find(secs, *exclusions)
    if body:
        rows, hdr = table(body)
        for svc, days, other in columns(rows, hdr, "Service", "within|Window", "Of this Service|Excluded by"):
            spec["exclusions"].append((svc, quantity(days), other))

    if caps:
        body = find(secs, *caps)
        if body:
            rows, hdr = table(body)
            for name, cap in columns(rows, hdr, "Service", "Maximum"):
                svc = spec["services"].get(name)
                q = quantity(cap)
                if svc is None:
                    spec["warnings"].append(f"caps: unknown service {name!r}")
                elif svc["daily_cap"] is None:
                    svc["daily_cap"] = q
                elif svc["daily_cap"] != q:
                    spec["warnings"].append(
                        f"caps: disagrees with rate schedule for {name!r}: {svc['daily_cap']} vs {q}")


def _validate(spec):
    _check_known(spec, spec["threshold_premiums"], "premiums")
    _check_known(spec, spec["nbd_uplifts"], "nbd uplifts")
    _check_known(spec, spec["volume_discounts"], "volume discounts")
    _check_known(spec, [n for t in spec["bundles"] for n in t[:2]], "bundles")
    _check_known(spec, [n for t in spec["exclusions"] for n in (t[0], t[2])], "exclusions")
    _check_known(spec, spec["facility_multipliers"], "facility multipliers")
    _check_known(spec, spec["tier_multipliers"], "tier multipliers")
    return spec


def _rate_schedule(spec, body, provenance):
    """A `Service | Unit basis | Rate | Daily cap` table."""
    rows, hdr = table(body)
    for row in columns(rows, hdr, "Service", "Unit basis", "Rate", "Daily cap"):
        name, basis, rate, cap = row
        spec["services"][name] = new_service(name, UNIT_BASIS[basis], [new_rate(cents(rate))],
                                             quantity(cap) if cap else None)
    spec["provenance"]["services"] = provenance


def _doc(data_root, hospital, stem):
    return open(f"{data_root}/contracts/{hospital}/{stem}.md").read()


# hospital 1 - a single document, one table per rule family

def compile_hospital_1(data_root, hospital="hospital_1"):
    hdr = read_header(data_root, hospital)
    secs = sections(_doc(data_root, hospital, "provider_services_agreement"))
    spec = new_spec(hospital, hdr["contract_number"], hdr["effective_from"], hdr["effective_to"])

    _rate_schedule(spec, find(secs, "Rate Schedule"), "s4 Rate Schedule")
    _read_rule_tables(spec, secs,
                      premiums=("Threshold Premiums",), nbd=("Non-Business-Day",),
                      discounts=("Volume Discounts",), bundles=("Bundled Services",),
                      exclusions=("Exclusion Windows",), caps=("Daily Quantity Caps",))
    spec["provenance"].update({"premiums": "s5", "nbd": "s6", "discounts": "s7",
                               "caps": "s4 + s8 (cross-checked)", "bundles": "s9",
                               "exclusions": "s10"})
    return _validate(spec)


# hospital 3 - three documents, and an amendment that reprices by service date

AMENDMENT_START = date(2025, 1, 1)

def compile_hospital_3(data_root, hospital="hospital_3"):
    """Base agreement + Appendix B rates + Amendment No. 1.

    The amendment "applies by Service Date. A line item whose Service Date falls on or
    after the effective date is priced under this Amendment; a line item whose Service
    Date falls before the effective date is priced under Appendix B. The date on which
    an invoice is issued is irrelevant." So an amended service carries two rates, each
    bounded in time, and the engine picks by service date.
    """
    hdr = read_header(data_root, hospital)
    base = sections(_doc(data_root, hospital, "base_agreement"))
    appendix = sections(_doc(data_root, hospital, "appendix_b_rate_schedule"))
    amendment = sections(_doc(data_root, hospital, "amendment_no_1"))

    spec = new_spec(hospital, hdr["contract_number"], hdr["effective_from"], hdr["effective_to"])
    _rate_schedule(spec, find(appendix, "B.1", "Rates"), "Appendix B.1 Rates")

    # A1.2 substitutes rates from 1 Jan 2025; both periods are stated explicitly.
    rows, h = table(find(amendment, "Substituted Rates"))
    for name, basis, before, after in columns(rows, h, "Service", "Unit basis",
                                              "to 31 December 2024", "from 1 January 2025"):
        if name not in spec["services"]:
            spec["warnings"].append(f"A1.2: substitutes unknown service {name!r}")
            continue
        spec["services"][name]["rates"] = [
            new_rate(cents(before), valid_to=AMENDMENT_START.replace(year=2024, month=12, day=31)),
            new_rate(cents(after), valid_from=AMENDMENT_START),
        ]

    # A1.3 adds services that "are not billable in respect of earlier Service Dates".
    rows, h = table(find(amendment, "Additional Services"))
    for name, basis, rate in columns(rows, h, "Service", "Unit basis", "Rate"):
        spec["services"][name] = new_service(name, UNIT_BASIS[basis],
                                             [new_rate(cents(rate), valid_from=AMENDMENT_START)])
    spec["provenance"]["amendment"] = "Amendment No. 1 A1.2/A1.3, applied by service date"

    _read_rule_tables(spec, base,
                      premiums=("Threshold Premiums",), nbd=("Non-Business-Day",),
                      discounts=("Volume Discounts",), bundles=("Bundled Services",),
                      exclusions=("Exclusion Windows",), caps=("Daily Quantity Caps",))
    spec["provenance"].update({"premiums": "base s4", "nbd": "base s5", "discounts": "base s6",
                               "caps": "Appendix B.1 + base s7", "bundles": "base s8",
                               "exclusions": "base s9"})
    return _validate(spec)


# hospital 4 - single document; rates carry no cap column, caps are their own table

def compile_hospital_4(data_root, hospital="hospital_4"):
    hdr = read_header(data_root, hospital)
    secs = sections(_doc(data_root, hospital, "conditional_reimbursement_agreement"))
    spec = new_spec(hospital, hdr["contract_number"], hdr["effective_from"], hdr["effective_to"])

    rows, h = table(find(secs, "Base Rates"))
    for name, basis, rate in columns(rows, h, "Service", "Unit basis", "Base rate"):
        spec["services"][name] = new_service(name, UNIT_BASIS[basis], [new_rate(cents(rate))])
    spec["provenance"]["services"] = "s3 Base Rates"

    _read_rule_tables(spec, secs,
                      premiums=("Threshold Premiums",), nbd=("Non-Business-Day",),
                      discounts=("Discounts",), bundles=("Bundled Delivery",),
                      exclusions=("Exclusion Windows",), caps=("Daily Quantity Limits",))
    spec["provenance"].update({"premiums": "s5", "caps": "s6", "bundles": "s7",
                               "discounts": "s8", "exclusions": "s9",
                               "nbd": "s10 (states 'None.')"})
    return _validate(spec)


# hospital 5 - a facility x plan-tier multiplier grid over a base rate table

def compile_hospital_5(data_root, hospital="hospital_5"):
    hdr = read_header(data_root, hospital)
    secs = sections(_doc(data_root, hospital, "network_reimbursement_agreement"))
    spec = new_spec(hospital, hdr["contract_number"], hdr["effective_from"], hdr["effective_to"])

    rows, h = table(find(secs, "Table 1"))
    for name, basis, rate, cap in columns(rows, h, "Service", "Unit basis", "Base rate", "Daily cap"):
        spec["services"][name] = new_service(name, UNIT_BASIS[basis], [new_rate(cents(rate))],
                                             quantity(cap) if cap else None)
    spec["provenance"]["services"] = "s4 Table 1"

    for title, key in (("Table 2", "facility_multipliers"), ("Table 3", "tier_multipliers")):
        rows, h = table(find(secs, title))
        names = h[1:]                       # the contract names its own columns
        for row in rows:
            spec[key][row[0]] = {k: decimal_val(v) for k, v in zip(names, row[1:])}
        spec["provenance"][key] = f"s4 {title}"

    _read_rule_tables(spec, secs,
                      premiums=("Threshold Premiums",), nbd=("Non-Business-Day",),
                      discounts=("Volume Discounts",), bundles=("Bundled Services",),
                      exclusions=("Exclusion Windows",))
    spec["provenance"].update({"premiums": "s5", "nbd": "s6", "bundles": "s7",
                               "discounts": "s8", "exclusions": "s9"})
    return _validate(spec)


COMPILERS = {
    "hospital_1": compile_hospital_1,
    "hospital_3": compile_hospital_3,
    "hospital_4": compile_hospital_4,
    "hospital_5": compile_hospital_5,
}


def compile_contract(data_root, hospital):
    """Compile one hospital's contract. Hospital 2 is prose and needs `extract`."""
    if hospital not in COMPILERS:
        raise NotImplementedError(f"{hospital} has no table-based compiler (it is prose)")
    return COMPILERS[hospital](data_root, hospital)
