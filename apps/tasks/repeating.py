"""Repeating tasks: regular advisory work with no statutory deadline."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps import events
from apps.core.dates import add_months

from . import services
from .models import RepeatingTask, Task, TaskKind

MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
DAYS = {"weekly": 7, "fortnightly": 14}


def period_start(rule: RepeatingTask, n: int) -> date:
    """The start of period number n (0 is the first). Months count from the first date."""
    if rule.frequency in DAYS:
        return rule.first_date + timedelta(days=DAYS[rule.frequency] * n)
    return add_months(rule.first_date, MONTHS[rule.frequency] * n)


def current_period(rule: RepeatingTask, today: date) -> date | None:
    """The latest period that has started by today, or None if the first has not."""
    if today < rule.first_date:
        return None
    n = 0
    # Walk forward; at most a few hundred steps even for a weekly rule from years ago.
    step = {"weekly": 7, "fortnightly": 14}.get(rule.frequency)
    if step:
        n = (today - rule.first_date).days // step
    else:
        n = (
            (today.year - rule.first_date.year) * 12 + today.month - rule.first_date.month
        ) // MONTHS[rule.frequency]
        while n > 0 and period_start(rule, n) > today:
            n -= 1
        while period_start(rule, n + 1) <= today:
            n += 1
    return period_start(rule, n)


def label_for(rule: RepeatingTask, start: date) -> str:
    if rule.frequency in DAYS:
        return (
            f"Week of {start:%d/%m/%Y}" if rule.frequency == "weekly" else f"From {start:%d/%m/%Y}"
        )
    if rule.frequency == "monthly":
        return start.strftime("%B %Y")
    if rule.frequency == "quarterly":
        return f"Quarter from {start:%d/%m/%Y}"
    return f"Year from {start:%d/%m/%Y}"


def create_due(today: date | None = None, *, actor=None) -> dict:
    """Make the task for the current period of each active rule. Safe to run twice.

    A period that was missed while nothing ran is skipped, not made late. A rule stops
    after its end date, and when it is switched off.
    """
    today = today or timezone.localdate()
    made = 0
    for rule in RepeatingTask.objects.filter(active=True).select_related(
        "client", "owner", "category"
    ):
        start = current_period(rule, today)
        if start is None or (rule.ends_on and start > rule.ends_on):
            continue
        if Task.objects.filter(repeating_task=rule, start_date=start).exists():
            continue
        try:
            with transaction.atomic():
                services.create_task(
                    actor,
                    title=rule.title,
                    client=rule.client,
                    kind=TaskKind.ADVISORY,
                    category=rule.category,
                    owner=rule.owner,
                    target_date=start + timedelta(days=rule.days_until_due),
                    start_date=start,
                    period_label=label_for(rule, start),
                    source=Task.Source.REPEATING,
                    repeating_task=rule,
                )
        except IntegrityError:
            continue  # made by another run a moment ago
        made += 1
    return {"created": made}


def save(actor, rule: RepeatingTask) -> RepeatingTask:
    if not rule.title.strip():
        raise ValidationError("Give the task a title.")
    creating = rule.pk is None
    if creating:
        rule.created_by = actor
    rule.save()
    events.record(
        actor,
        "repeating.created" if creating else "repeating.changed",
        f"{services.who(actor)} {'created' if creating else 'changed'} the repeating task "
        f"{rule.title} ({rule.get_frequency_display().lower()}).",
        client=rule.client,
        target=rule,
    )
    return rule
