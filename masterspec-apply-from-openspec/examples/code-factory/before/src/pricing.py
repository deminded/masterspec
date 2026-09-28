"""Existing implementation: integer payable amount, no breakdown."""
from decimal import Decimal, ROUND_HALF_UP


def quote(subtotal: Decimal) -> Decimal:
    return (subtotal * Decimal("1.20")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
