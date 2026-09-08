"""Exact money.

Every contract states the same rounding convention (H1 s3.1, H2 s3.1, H5 s3.2):

    Where the application of a multiplier, premium or discount produces a
    fraction of a cent, the result shall be rounded to the nearest whole cent,
    with exact halves rounded away from zero ("half up"). Rounding is applied
    after each individual step of the calculation, not once at the end.

We implement "after each individual step" literally: `apply` rounds on every
call and the engine calls it once per step.

Measured, not assumed, and the two hospitals disagree:

  hospital 1   0 of   109 rate combinations differ between the two conventions
  hospital 5 115 of 1,062 rate combinations differ (10.83%)

Hospital 1 chains at most a premium and a discount, so the conventions are
indistinguishable there and the dev set cannot validate this choice at all.
Hospital 5 chains four multipliers — facility, plan tier, premium, discount —
and one rate in nine comes out a cent apart.

That makes the reading checkable: under step-rounding 99.3% of hospital 5 line
items reproduce their billed amount exactly. Under the alternative, roughly a
tenth of all rates would be off by a cent and would surface as spurious
`unit_price_mismatch` findings across the whole hospital. The agreement is the
evidence that the contract means what it says.

Decimal, never float. `0.1 + 0.2 != 0.3` is not an acceptable property for a
system that decides whether a hospital was overpaid.
"""

from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)


def half_up(value):
    """Round a Decimal to the nearest whole cent, halves away from zero."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def apply(cents, factor):
    """One adjustment step: multiply and round half-up immediately."""
    return half_up(Decimal(cents) * Decimal(factor))


def uplift(cents, fraction):
    """Apply a premium of `fraction` (0.20 -> +20%)."""
    return apply(cents, ONE + Decimal(fraction))


def discount(cents, fraction):
    """Apply a discount of `fraction` (0.10 -> -10%)."""
    return apply(cents, ONE - Decimal(fraction))
