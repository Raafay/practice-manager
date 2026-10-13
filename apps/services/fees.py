"""Fee arithmetic. Money is in pounds, excluding VAT, rounded half up to pence."""

from decimal import Decimal

from apps.core.money import to_pounds

DIVISORS = {"monthly": 1, "quarterly": 3, "annual": 12}


def monthly_equivalent(amount, frequency: str) -> Decimal | None:
    """Pounds a month. None when there is no fee; one-off fees count as 0 recurring."""
    if amount is None:
        return None
    divisor = DIVISORS.get(frequency)
    if divisor is None:
        return Decimal("0.00")
    return to_pounds(Decimal(amount) / divisor)


def totals(client_services) -> tuple[Decimal, Decimal]:
    """(monthly recurring total, one-off total). Each service is rounded before adding."""
    monthly = Decimal("0.00")
    one_off = Decimal("0.00")
    for row in client_services:
        if row.fee_amount is None:
            continue
        if row.fee_frequency == "one_off":
            one_off += Decimal(row.fee_amount)
        else:
            monthly += monthly_equivalent(row.fee_amount, row.fee_frequency)
    return monthly, one_off
