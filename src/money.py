"""Money arithmetic. Decimal only, never float, and round half-up after every step,
because every contract says so.
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
