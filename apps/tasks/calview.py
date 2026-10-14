"""The calendar: month and week grids built on the server."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from apps.core.dates import add_months
from apps.services.models import Deadline

from .models import Task

LAYOUTS = [("month", "Month"), ("week", "Week")]
LAYOUT_KEYS = {key for key, _ in LAYOUTS}
ON = [("target", "Target date"), ("due", "Deadline")]
ON_KEYS = {key for key, _ in ON}
SIDE_LIMIT = 50


@dataclass
class Day:
    date: date
    in_range: bool = True
    today: bool = False
    weekend: bool = False
    tasks: list[Task] = field(default_factory=list)
    markers: list[Deadline] = field(default_factory=list)


def parse_anchor(raw: str, today: date) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return today


def bounds(layout: str, anchor: date) -> tuple[date, date, date, date]:
    """(first day of the grid, last day of the grid, first day of the period, last day)."""
    if layout == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6), start, start + timedelta(days=6)
    first = anchor.replace(day=1)
    last = add_months(first, 1) - timedelta(days=1)
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6 - last.weekday())
    return start, end, first, last


def neighbours(layout: str, anchor: date) -> tuple[date, date]:
    if layout == "week":
        return anchor - timedelta(days=7), anchor + timedelta(days=7)
    first = anchor.replace(day=1)
    return add_months(first, -1), add_months(first, 1)


def title(layout: str, first: date, last: date) -> str:
    if layout == "week":
        return f"{first:%d/%m/%Y} to {last:%d/%m/%Y}"
    return first.strftime("%B %Y")


def build(
    queryset,
    *,
    layout: str,
    anchor: date,
    on: str,
    client=None,
    today: date | None = None,
) -> dict:
    today = today or timezone.localdate()
    layout = layout if layout in LAYOUT_KEYS else "month"
    on = on if on in ON_KEYS else "target"
    start, end, first, last = bounds(layout, anchor)
    column = "due_date" if on == "due" else "target_date"

    tasks = (
        queryset.filter(**{f"{column}__range": (start, end)})
        .select_related("client", "owner", "category", "status")
        .order_by(column, "id")
    )
    days = {
        start + timedelta(days=n): Day(
            start + timedelta(days=n),
            in_range=first <= start + timedelta(days=n) <= last,
            today=start + timedelta(days=n) == today,
            weekend=(start + timedelta(days=n)).weekday() >= 5,
        )
        for n in range((end - start).days + 1)
    }
    for task in tasks:
        task.tone = task.deadline_tone(today)
        days[getattr(task, column)].tasks.append(task)

    markers = Deadline.objects.open().filter(due_date__range=(start, end)).select_related("client")
    if client is not None:
        markers = markers.filter(client=client)
    for marker in markers.order_by("due_date", "label"):
        days[marker.due_date].markers.append(marker)

    side = (
        queryset.filter(**{f"{column}__isnull": True})
        .select_related("client", "owner", "category", "status")
        .order_by("due_date", "id")[:SIDE_LIMIT]
    )
    weeks = [
        [days[start + timedelta(days=7 * w + d)] for d in range(7)] for w in range(len(days) // 7)
    ]
    before, after = neighbours(layout, anchor)
    return {
        "cal_layout": layout,
        "cal_on": on,
        "cal_title": title(layout, first, last),
        "weeks": weeks,
        "side_tasks": list(side),
        "cal_prev": before,
        "cal_next": after,
        "cal_today": today,
        "cal_locked": on == "due",
        "weekday_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    }
