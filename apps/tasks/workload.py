"""Workload: open work per person, and estimated hours against capacity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import User

from .filters import between_q, overdue_q, week_bounds
from .models import Task

WINDOW_DAYS = 14
AMBER = 85
RED = 100


@dataclass
class Row:
    user: User | None
    label: str
    open: int = 0
    overdue: int = 0
    this_week: int = 0
    next_week: int = 0
    estimate_minutes: int = 0
    without_estimate: int = 0
    capacity_hours: Decimal | None = None
    logged_minutes: int = 0  # time logged this week (Stage 11)

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.estimate_minutes) / Decimal(60)).quantize(Decimal("0.1"))

    @property
    def logged_hours(self) -> Decimal:
        return (Decimal(self.logged_minutes) / Decimal(60)).quantize(Decimal("0.1"))

    @property
    def percent(self) -> int | None:
        if not self.capacity_hours:
            return None
        return int(Decimal(self.estimate_minutes) / Decimal(60) * 100 / self.capacity_hours)

    @property
    def tone(self) -> str:
        percent = self.percent
        if percent is None:
            return "neutral"
        if percent > RED:
            return "red"
        if percent > AMBER:
            return "amber"
        return "green"

    @property
    def bar(self) -> int:
        return min(self.percent or 0, 100)

    @property
    def owner_param(self) -> str:
        return str(self.user.pk) if self.user else "none"


def build(today: date | None = None) -> list[Row]:
    """One row per active staff member and one for unassigned work."""
    today = today or timezone.localdate()
    this_first, this_last = week_bounds(today)
    next_first, next_last = week_bounds(today + timedelta(days=7))
    window_end = today + timedelta(days=WINDOW_DAYS - 1)
    in_window = Q(target_date__range=(today, window_end)) | Q(
        target_date__isnull=True, due_date__range=(today, window_end)
    )
    rows = (
        Task.objects.open()
        .values("owner_id")
        .annotate(
            n_open=Count("id"),
            n_overdue=Count("id", filter=overdue_q(today)),
            n_week=Count("id", filter=between_q(this_first, this_last)),
            n_next=Count("id", filter=between_q(next_first, next_last)),
            minutes=Sum("estimate_minutes", filter=in_window, default=0),
            n_blank=Count("id", filter=in_window & Q(estimate_minutes__isnull=True)),
        )
    )
    by_owner = {row["owner_id"]: row for row in rows}
    result = []

    def fill(row: Row, data: dict | None):
        if data:
            row.open = data["n_open"]
            row.overdue = data["n_overdue"]
            row.this_week = data["n_week"]
            row.next_week = data["n_next"]
            row.estimate_minutes = data["minutes"] or 0
            row.without_estimate = data["n_blank"]
        return row

    from apps.timekeeping.models import TimeEntry

    logged = dict(
        TimeEntry.objects.filter(date__range=(this_first, this_last))
        .values_list("user_id")
        .annotate(total=Sum("minutes"))
    )
    for user in User.objects.staff().filter(is_active=True).order_by("name"):
        row = Row(user, user.name, capacity_hours=user.weekly_hours * 2)
        row.logged_minutes = logged.get(user.pk, 0)
        result.append(fill(row, by_owner.get(user.pk)))
    result.append(fill(Row(None, "Unassigned"), by_owner.get(None)))
    return result
