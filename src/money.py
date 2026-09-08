"""Exact money.

Every contract states the same rounding convention (H1 s3.1, H2 s3.1, H5 s3.2):

    Where the application of a multiplier, premium or discount produces a
    fraction of a cent, the result shall be rounded to the nearest whole cent,
    with exact halves rounded away from zero ("half up"). Rounding is applied
    after each individual step of the calculation, not once at the end.

We implement "after each individual step" literally: `apply` rounds on every
call and the engine calls it once per step.

Measured, not assumed: across every rate x premium x discount combination in
the hospital_1 schedule, step-rounding and rounding-once-at-the-end agree on
all of them. So this convention costs nothing on hospital 1 and cannot be
validated there. It is implemented because the contract mandates it, and
because hospital 5 chains up to four multipliers (facility, plan tier, premium,
discount) where the two conventions have far more room to diverge. Whether they
actually do on hospital 5 is checked in the evaluation, not assumed here.

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
