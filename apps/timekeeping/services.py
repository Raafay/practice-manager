"""Time tracking rules: timers, entries, the weekly grid and totals."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps import events

from .models import TimeEntry, Timer

MAX_MINUTES_PER_ENTRY = 24 * 60


def format_minutes(minutes: int | None) -> str:
    """1h 30m style text. Empty for nothing."""
    if not minutes:
        return ""
    hours, rest = divmod(int(minutes), 60)
    if hours and rest:
        return f"{hours}h {rest:02d}m"
    return f"{hours}h" if hours else f"{rest}m"


def clock_text(minutes: int | None) -> str:
    """1:30 style text for the timesheet boxes. Empty for nothing."""
    if not minutes:
        return ""
    hours, rest = divmod(int(minutes), 60)
    return f"{hours}:{rest:02d}"


_CLOCK = re.compile(r"^(\d{1,2}):([0-5]\d)$")
_UNITS = re.compile(r"^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*m)?$", re.I)


def parse_duration(text: str) -> int:
    """Minutes from '1:30', '1.5', '90m', '1h 30m' or '2h'. Raises ValidationError."""
    value = (text or "").strip().lower()
    if not value:
        raise ValidationError("Enter the time as hours and minutes, for example 1:30 or 1.5.")
    minutes = None
    if match := _CLOCK.match(value):
        minutes = int(match[1]) * 60 + int(match[2])
    elif re.fullmatch(r"\d+(\.\d+)?", value):
        minutes = int((Decimal(value) * 60).quantize(Decimal("1")))
    elif (match := _UNITS.match(value)) and (match[1] or match[2]):
        minutes = int((Decimal(match[1] or 0) * 60).quantize(Decimal("1"))) + int(match[2] or 0)
    if minutes is None:
        raise ValidationError("Enter the time as hours and minutes, for example 1:30 or 1.5.")
    if minutes <= 0:
        raise ValidationError("The time must be more than zero.")
    if minutes > MAX_MINUTES_PER_ENTRY:
        raise ValidationError("An entry cannot be longer than 24 hours.")
    return minutes


def who(user) -> str:
    return getattr(user, "name", "") or str(user)


def can_edit(user, entry: TimeEntry) -> bool:
    return entry.user_id == user.pk or user.can("time.edit_all")


def _clean_links(client, task, service):
    """A task brings its client with it, so the three never disagree."""
    if task is not None:
        if client is not None and task.client_id and task.client_id != client.pk:
            raise ValidationError("That task belongs to a different client.")
        client = client or task.client
    return client, task, service


# ---------------------------------------------------------------- entries


@transaction.atomic
def log_time(
    actor,
    *,
    minutes: int,
    on_date: date | None = None,
    client=None,
    task=None,
    service=None,
    note: str = "",
    billable: bool = True,
    user=None,
    started_at=None,
    ended_at=None,
) -> TimeEntry:
    """Save one entry. `user` is who the time is for (default: the actor)."""
    user = user or actor
    if user.pk != actor.pk and not actor.can("time.edit_all"):
        raise PermissionDenied
    if minutes <= 0 or minutes > MAX_MINUTES_PER_ENTRY:
        raise ValidationError("The time must be between a minute and 24 hours.")
    client, task, service = _clean_links(client, task, service)
    entry = TimeEntry.objects.create(
        user=user,
        client=client,
        task=task,
        service=service,
        date=on_date or timezone.localdate(),
        minutes=minutes,
        note=note[:300],
        billable=billable,
        started_at=started_at,
        ended_at=ended_at,
    )
    events.record(
        actor,
        "time.logged",
        f"{who(actor)} logged {format_minutes(minutes)}"
        + (f" for {client.name}" if client else " (internal)")
        + (f" for {who(user)}" if user.pk != actor.pk else "")
        + ".",
        client=client,
        target=entry,
        minutes=minutes,
    )
    return entry


@transaction.atomic
def update_entry(actor, entry: TimeEntry, **fields) -> TimeEntry:
    if not can_edit(actor, entry):
        raise PermissionDenied
    client = fields.get("client", entry.client)
    task = fields.get("task", entry.task)
    service = fields.get("service", entry.service)
    fields["client"], fields["task"], fields["service"] = _clean_links(client, task, service)
    minutes = fields.get("minutes", entry.minutes)
    if minutes <= 0 or minutes > MAX_MINUTES_PER_ENTRY:
        raise ValidationError("The time must be between a minute and 24 hours.")
    for name, value in fields.items():
        setattr(entry, name, value)
    entry.save()
    events.record(
        actor,
        "time.changed",
        f"{who(actor)} changed a time entry of {format_minutes(entry.minutes)}.",
        client=entry.client,
        target=entry,
    )
    return entry


@transaction.atomic
def delete_entry(actor, entry: TimeEntry) -> None:
    if not can_edit(actor, entry):
        raise PermissionDenied
    events.record(
        actor,
        "time.deleted",
        f"{who(actor)} deleted a time entry of {format_minutes(entry.minutes)}.",
        client=entry.client,
        minutes=entry.minutes,
    )
    entry.delete()


# ---------------------------------------------------------------- timers


def running_timer(user) -> Timer | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return Timer.objects.select_related("client", "task").filter(user=user).first()


@transaction.atomic
def stop_timer(user, *, now: datetime | None = None) -> TimeEntry | None:
    """Stop the user's timer and save an entry. A run under a minute counts as one minute."""
    timer = Timer.objects.select_for_update(of=("self",)).select_related("client", "task")
    timer = timer.filter(user=user).first()
    if timer is None:
        return None
    now = now or timezone.now()
    seconds = max((now - timer.started_at).total_seconds(), 0)
    minutes = min(max(int(round(seconds / 60)), 1), MAX_MINUTES_PER_ENTRY)
    started = timer.started_at
    client, task = timer.client, timer.task
    timer.delete()
    return log_time(
        user,
        minutes=minutes,
        on_date=timezone.localtime(started).date(),
        client=client,
        task=task,
        started_at=started,
        ended_at=now,
    )


@transaction.atomic
def start_timer(user, *, client=None, task=None, now: datetime | None = None) -> Timer:
    """Start a timer. A timer already running is stopped first and saved."""
    client, task, _ = _clean_links(client, task, None)
    stop_timer(user, now=now)
    try:
        with transaction.atomic():
            timer = Timer.objects.create(
                user=user, client=client, task=task, started_at=now or timezone.now()
            )
    except IntegrityError:  # two requests at once: the second finds one running
        raise ValidationError("A timer is already running.") from None
    events.record(
        user,
        "time.timer_started",
        f"{who(user)} started a timer for {timer.label}.",
        client=client,
        target=timer,
    )
    return timer


# ---------------------------------------------------------------- timesheet


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_days(start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(7)]


def week_grid(user, start: date) -> dict:
    """Rows of (client, task) with minutes for each day, plus daily and weekly totals."""
    days = week_days(start)
    entries = list(
        TimeEntry.objects.filter(user=user, date__range=(days[0], days[-1])).select_related(
            "client", "task"
        )
    )
    rows: dict[tuple, dict] = {}
    for entry in entries:
        key = (entry.client_id, entry.task_id)
        row = rows.setdefault(
            key,
            {
                "client": entry.client,
                "task": entry.task,
                "cells": {d: {"minutes": 0, "count": 0, "entry": None} for d in days},
            },
        )
        cell = row["cells"][entry.date]
        cell["minutes"] += entry.minutes
        cell["count"] += 1
        cell["entry"] = entry if cell["count"] == 1 else None
    out = []
    for row in sorted(
        rows.values(),
        key=lambda r: (
            (r["client"].name if r["client"] else "~"),
            (r["task"].title if r["task"] else ""),
        ),
    ):
        row["cells"] = [{"day": d, **row["cells"][d]} for d in days]
        row["total"] = sum(c["minutes"] for c in row["cells"])
        out.append(row)
    daily = [sum(r["cells"][i]["minutes"] for r in out) for i in range(7)]
    weekly = sum(daily)
    capacity = Decimal(user.weekly_hours) * 60
    return {
        "days": days,
        "rows": out,
        "daily": daily,
        "weekly": weekly,
        "capacity_minutes": int(capacity),
        "percent": int(Decimal(weekly) * 100 / capacity) if capacity else None,
    }


def set_cell(actor, user, *, client, task, on_date: date, minutes: int | None) -> TimeEntry | None:
    """Set one timesheet box: edit its one entry, make one, or refuse when it holds several."""
    if user.pk != actor.pk and not actor.can("time.edit_all"):
        raise PermissionDenied
    existing = list(TimeEntry.objects.filter(user=user, client=client, task=task, date=on_date))
    if len(existing) > 1:
        raise ValidationError("This box holds several entries. Edit them from the list.")
    if minutes is None:
        if existing:
            delete_entry(actor, existing[0])
        return None
    if existing:
        return update_entry(actor, existing[0], minutes=minutes)
    return log_time(actor, minutes=minutes, on_date=on_date, client=client, task=task, user=user)


# ---------------------------------------------------------------- totals


def minutes_by(queryset, field: str) -> list[tuple]:
    rows = queryset.values(field).annotate(total=Sum("minutes")).order_by("-total")
    return [(row[field], row["total"]) for row in rows]


def client_totals(client) -> dict:
    """Totals by month, by service and by person for a client's Time tab."""
    entries = TimeEntry.objects.filter(client=client)
    by_month: dict[str, int] = defaultdict(int)
    for day, minutes in entries.values_list("date", "minutes"):
        by_month[f"{day:%Y-%m}"] += minutes
    by_service = defaultdict(int)
    for name, minutes in entries.values_list("service__name", "minutes"):
        by_service[name or "No service"] += minutes
    by_person = defaultdict(int)
    for name, minutes in entries.values_list("user__name", "minutes"):
        by_person[name] += minutes
    total = sum(by_month.values())
    return {
        "months": sorted(by_month.items(), reverse=True),
        "services": sorted(by_service.items(), key=lambda kv: -kv[1]),
        "people": sorted(by_person.items(), key=lambda kv: -kv[1]),
        "total": total,
    }


def task_minutes(task) -> int:
    return task.time_entries.aggregate(total=Sum("minutes"))["total"] or 0


def minutes_this_week(user, today: date | None = None) -> int:
    start = week_start(today or timezone.localdate())
    return (
        TimeEntry.objects.filter(
            user=user, date__range=(start, start + timedelta(days=6))
        ).aggregate(total=Sum("minutes"))["total"]
        or 0
    )
