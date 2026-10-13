"""Money is stored in pounds as Decimal(10, 2), excluding VAT."""

from decimal import ROUND_HALF_UP, Decimal

PENNY = Decimal("0.01")


def to_pounds(value) -> Decimal:
    return Decimal(str(value)).quantize(PENNY, rounding=ROUND_HALF_UP)


def format_money(value, *, pence: bool = True) -> str:
    """Format as £1,234.50 (or £1,235 with pence=False). Empty for None."""
    if value is None or value == "":
        return ""
    amount = to_pounds(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if pence:
        return f"{sign}£{amount:,.2f}"
    return f"{sign}£{amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}"
