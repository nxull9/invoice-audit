"""Flattening every contract into one table.

Five contracts arrive in five layouts -- tables, prose, three documents, a PDF -- and
become one row per service per rate period, with identical columns whatever the source.
That table is the only thing the pricing engine reads, so a sixth provider in a sixth
format changes nothing downstream.

It is also the reviewable artefact. Written to CSV it is a few hundred rows an auditor
can read against the contract itself, which a nested specification object is not.
"""

import pandas as pd

from src.contract_spec import bundle_partner

COLUMNS = [
    "hospital", "contract_number", "service", "unit_basis",
    "rate_cents", "valid_from", "valid_to", "daily_cap",
    "nbd_uplift_pct", "premium_threshold", "premium_uplift_pct",
    "discount_threshold", "discount_pct",
    "bundle_partner", "bundle_rate_cents",
    "facility_multipliers", "tier_multipliers",
    "source_route", "extraction_confidence",
]


def _pct(value):
    return None if value is None else round(float(value) * 100, 4)


def spec_to_table(spec, source_route="text", extraction_confidence=1.0):
    """One row per service per rate period, in the shared column set."""
    rows = []
    for name, service in sorted(spec["services"].items()):
        premium = spec["threshold_premiums"].get(name)
        discounts = spec["volume_discounts"].get(name) or [(None, None)]
        partner, bundle_rate = bundle_partner(spec, name)
        facility = spec["facility_multipliers"].get(name) or {}
        tier = spec["tier_multipliers"].get(name) or {}

        for rate in service["rates"]:
            # A service with two discount tiers yields two rows; the engine applies the
            # deeper one, and both are shown so the schedule is checkable by eye.
            for threshold, fraction in discounts:
                rows.append({
                    "hospital": spec["hospital"],
                    "contract_number": spec["contract_number"],
                    "service": name,
                    "unit_basis": service["unit_basis"],
                    "rate_cents": rate["cents"],
                    "valid_from": rate["valid_from"],
                    "valid_to": rate["valid_to"],
                    "daily_cap": service["daily_cap"],
                    "nbd_uplift_pct": _pct(spec["nbd_uplifts"].get(name)),
                    "premium_threshold": premium[0] if premium else None,
                    "premium_uplift_pct": _pct(premium[1]) if premium else None,
                    "discount_threshold": threshold,
                    "discount_pct": _pct(fraction),
                    "bundle_partner": partner,
                    "bundle_rate_cents": bundle_rate,
                    "facility_multipliers": ";".join(
                        f"{k}={v}" for k, v in sorted(facility.items())) or None,
                    "tier_multipliers": ";".join(
                        f"{k}={v}" for k, v in sorted(tier.items())) or None,
                    "source_route": source_route,
                    "extraction_confidence": extraction_confidence,
                })
    return pd.DataFrame(rows, columns=COLUMNS)


def combine(tables):
    """All hospitals in one table, the form the engine and a reviewer both read."""
    return pd.concat(tables, ignore_index=True).sort_values(
        ["hospital", "service", "valid_from"], na_position="first").reset_index(drop=True)


def summarise(table):
    """What each contract contributed, for checking nothing was dropped."""
    return (table.groupby("hospital")
            .agg(services=("service", "nunique"),
                 rows=("service", "size"),
                 rate_periods=("rate_cents", "size"),
                 with_cap=("daily_cap", lambda s: s.notna().sum()),
                 with_premium=("premium_threshold", lambda s: s.notna().sum()),
                 with_discount=("discount_threshold", lambda s: s.notna().sum()),
                 with_bundle=("bundle_partner", lambda s: s.notna().sum()),
                 route=("source_route", "first"),
                 confidence=("extraction_confidence", "min"))
            .reset_index())
