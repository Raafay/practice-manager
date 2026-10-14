"""Targets: the monthly recurring income wanted in each month, and the quick fills."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.db import transaction

from apps import events
from apps.core.dates import add_months
from apps.core.money import to_pounds

from .models import Target

MONTHS_SHOWN = 12


def months_from(start: date, count: int = MONTHS_SHOWN) -> list[date]:
    first = start.replace(day=1)
    return [add_months(first, i) for i in range(count)]


def spread_evenly(total: Decimal, count: int = MONTHS_SHOWN) -> list[Decimal]:
    """A yearly figure shared evenly in whole pence. The last month takes any odd pennies."""
    total = to_pounds(total)
    each = (total / count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    amounts = [each] * count
    amounts[-1] = total - each * (count - 1)
    return amounts


def straight_line(start: Decimal, end: Decimal, count: int = MONTHS_SHOWN) -> list[Decimal]:
    """A start and an end figure with a straight line between them."""
    start, end = to_pounds(start), to_pounds(end)
    if count == 1:
        return [start]
    step = (end - start) / (count - 1)
    return [to_pounds(start + step * i) for i in range(count)]


@transaction.atomic
def save_targets(actor, months: list[date], amounts: list[Decimal | None], *, how: str) -> int:
    """Set (or clear, for None) a target for each month. Returns how many months changed."""
    changed = 0
    for month, amount in zip(months, amounts, strict=True):
        existing = Target.objects.filter(month=month).first()
        if amount is None:
            if existing:
                existing.delete()
                changed += 1
            continue
        if amount < 0:
            raise ValueError("A target cannot be negative.")
        if existing is None:
            Target.objects.create(month=month, amount=amount)
            changed += 1
        elif existing.amount != amount:
            existing.amount = amount
            existing.save()
            changed += 1
    events.record(
        actor,
        "finance.targets_changed",
        f"{actor.name} changed the income targets ({how}) from {months[0]:%m/%Y} "
        f"to {months[-1]:%m/%Y}.",
        months=changed,
    )
    return changed
