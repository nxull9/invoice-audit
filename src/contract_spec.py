"""The one data structure every contract compiles into.

All five contracts encode the *same* pricing model. Hospital 1 states it in
tables, hospital 2 dissolves it into prose, hospital 3 splits it across three
documents and repriced part of it halfway through the term, hospital 5 adds a
facility x plan-tier multiplier grid. What differs is presentation, not
semantics — H1 s3.2, H2 s3.2 and H5 s3.1 state the identical adjustment order:

    (a) substitute a bundled rate
    (b) facility multiplier
    (c) plan-tier multiplier
    (d) premium or uplift
    (e) cumulative volume discount

with half-up rounding to the cent *after each step*.

So the engine is written once against this structure, and the per-hospital work
is compiling a `ContractSpec` — by regex where the contract is tabular, by LLM
where it is prose. `provenance` records where each rule came from, so an
extracted rule can always be traced back to the clause that produced it.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Rate:
    """A rate, optionally bounded in time.

    Hospital 3's Amendment No. 1 substitutes rates from 1 January 2025 *by
    service date*, so a service can hold several non-overlapping rates.
    """
    cents: int
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

    def covers(self, on):
        return ((self.valid_from is None or on >= self.valid_from)
                and (self.valid_to is None or on <= self.valid_to))


@dataclass
class Service:
    name: str
    unit_basis: str
    rates: list                      # list[Rate], newest-specific first
    daily_cap: Optional[int] = None  # max billable units per patient per service day

    def rate_on(self, service_date):
        """The contracted rate in force on a given service date, or None."""
        for r in self.rates:
            if r.covers(service_date):
                return r.cents
        return None


@dataclass
class ContractSpec:
    hospital: str
    contract_number: str
    effective_from: date
    effective_to: date

    services: dict = field(default_factory=dict)          # name -> Service
    threshold_premiums: dict = field(default_factory=dict)  # name -> (threshold_qty, uplift)
    nbd_uplifts: dict = field(default_factory=dict)         # name -> uplift fraction
    volume_discounts: dict = field(default_factory=dict)    # name -> [(threshold, fraction)]
    bundles: list = field(default_factory=list)             # [(a, b, rate_a, rate_b)]
    exclusions: list = field(default_factory=list)          # [(service, days, other)]
    facility_multipliers: dict = field(default_factory=dict)  # name -> {facility: mult}
    tier_multipliers: dict = field(default_factory=dict)      # name -> {tier: mult}

    provenance: dict = field(default_factory=dict)   # rule kind -> source location
    warnings: list = field(default_factory=list)     # anything we could not read cleanly

    # -- convenience -------------------------------------------------------
    def bundle_partner(self, service):
        """The service that must co-occur for a bundled rate, and the substituted rate."""
        for a, b, ra, rb in self.bundles:
            if service == a:
                return b, ra
            if service == b:
                return a, rb
        return None, None

    def summary(self):
        return {
            "hospital": self.hospital,
            "contract": self.contract_number,
            "services": len(self.services),
            "priced_periods": sum(len(s.rates) for s in self.services.values()),
            "daily_caps": sum(s.daily_cap is not None for s in self.services.values()),
            "threshold_premiums": len(self.threshold_premiums),
            "nbd_uplifts": len(self.nbd_uplifts),
            "volume_discounts": len(self.volume_discounts),
            "bundles": len(self.bundles),
            "exclusions": len(self.exclusions),
            "facility_multipliers": len(self.facility_multipliers),
            "tier_multipliers": len(self.tier_multipliers),
            "warnings": len(self.warnings),
        }
