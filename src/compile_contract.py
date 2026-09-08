"""Compiling a contract document into a ContractSpec.

One function per hospital, sharing the helpers in `markdown_tables`. Each
compiler is deliberately strict: a service named in a premium, discount, bundle
or exclusion table that does not appear in the rate schedule is recorded as a
warning rather than silently dropped, because a silently dropped rule prices
every invoice touching that service wrongly and does so invisibly.
"""

from src.config import CONTRACTS, UNIT_BASIS
from src.contract_spec import ContractSpec, Service, Rate
from src.contract_header import read_header
from src.markdown_tables import sections, table, find, cents, fraction, quantity


def _check_known(spec, names, where):
    """Record any service named by a rule table that the rate schedule lacks."""
    for n in names:
        if n not in spec.services:
            spec.warnings.append(f"{where}: unknown service {n!r} not in rate schedule")


def compile_hospital_1(hospital="hospital_1"):
    """Hospital 1 — a single document, one table per rule family."""
    hdr = read_header(hospital)
    text = (CONTRACTS / hospital / "provider_services_agreement.md").read_text()
    secs = sections(text)

    spec = ContractSpec(hospital=hospital, contract_number=hdr["contract_number"],
                        effective_from=hdr["effective_from"], effective_to=hdr["effective_to"])

    # s4 Rate Schedule: Service | Unit basis | Rate | Daily cap
    for name, basis, rate, cap in table(find(secs, "Rate Schedule"))[0]:
        spec.services[name] = Service(name=name, unit_basis=UNIT_BASIS[basis],
                                      rates=[Rate(cents(rate))],
                                      daily_cap=quantity(cap) if cap else None)
    spec.provenance["services"] = "s4 Rate Schedule"

    # s5 Threshold Premiums: Service | Applies when daily quantity exceeds | Uplift
    for name, threshold, uplift in table(find(secs, "Threshold Premiums"))[0]:
        spec.threshold_premiums[name] = (quantity(threshold), fraction(uplift))
    spec.provenance["threshold_premiums"] = "s5 Threshold Premiums"

    # s6 Non-Business-Day Uplifts: Service | Uplift
    for name, uplift in table(find(secs, "Non-Business-Day"))[0]:
        spec.nbd_uplifts[name] = fraction(uplift)
    spec.provenance["nbd_uplifts"] = "s6 Non-Business-Day Uplifts"

    # s7 Cumulative Volume Discounts: Service | threshold | Discount
    for name, threshold, disc in table(find(secs, "Volume Discounts"))[0]:
        spec.volume_discounts.setdefault(name, []).append((quantity(threshold), fraction(disc)))
    for name in spec.volume_discounts:                    # deepest threshold first
        spec.volume_discounts[name].sort(key=lambda t: -t[0])
    spec.provenance["volume_discounts"] = "s7 Cumulative Volume Discounts"

    # s8 Daily Quantity Caps restates the s4 cap column; use it to cross-check.
    for name, cap in table(find(secs, "Daily Quantity Caps"))[0]:
        q = quantity(cap)
        svc = spec.services.get(name)
        if svc is None:
            spec.warnings.append(f"s8: unknown service {name!r}")
        elif svc.daily_cap is None:
            svc.daily_cap = q
        elif svc.daily_cap != q:
            spec.warnings.append(f"s8: cap disagrees with s4 for {name!r}: {svc.daily_cap} vs {q}")
    spec.provenance["daily_caps"] = "s4 Rate Schedule + s8 Daily Quantity Caps (cross-checked)"

    # s9 Bundled Services: Service A | Service B | Bundled rate A | Bundled rate B
    for a, b, ra, rb in table(find(secs, "Bundled Services"))[0]:
        spec.bundles.append((a, b, cents(ra), cents(rb)))
    spec.provenance["bundles"] = "s9 Bundled Services"

    # s10 Exclusion Windows: Service | Not billable within | Of this Service
    for svc, days, other in table(find(secs, "Exclusion Windows"))[0]:
        spec.exclusions.append((svc, quantity(days), other))
    spec.provenance["exclusions"] = "s10 Exclusion Windows"

    _check_known(spec, spec.threshold_premiums, "s5")
    _check_known(spec, spec.nbd_uplifts, "s6")
    _check_known(spec, spec.volume_discounts, "s7")
    _check_known(spec, [n for t in spec.bundles for n in t[:2]], "s9")
    _check_known(spec, [n for t in spec.exclusions for n in (t[0], t[2])], "s10")
    return spec


COMPILERS = {"hospital_1": compile_hospital_1}


def compile_contract(hospital):
    if hospital not in COMPILERS:
        raise NotImplementedError(f"no compiler for {hospital} yet")
    return COMPILERS[hospital](hospital)
