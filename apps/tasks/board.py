"""The board: the same tasks as cards in columns, grouped by status, owner, category or client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client

from .models import ProjectSection, Task, TaskCategory, TaskStatus

DONE_WINDOW_DAYS = 14
COLUMN_LIMIT = 100
FETCH_LIMIT = 1500

MODES = [
    ("status", "Status"),
    ("owner", "Owner"),
    ("category", "Category"),
    ("client", "Client"),
    ("section", "Section"),
]
MODE_KEYS = {key for key, _ in MODES}
DEFAULT_MODE = "status"


@dataclass
class Column:
    key: str  # "none" for the empty column
    label: str
    colour: str = ""
    tasks: list[Task] = field(default_factory=list)
    total: int = 0
    note: str = ""

    @property
    def hidden(self) -> int:
        return self.total - len(self.tasks)


def valid_mode(value: str, *, project: bool = False) -> str:
    if value == "section" and not project:
        return DEFAULT_MODE
    return value if value in MODE_KEYS else DEFAULT_MODE


def done_cutoff(today: date | None = None) -> datetime:
    today = today or timezone.localdate()
    midnight = datetime.combine(today, time.min, tzinfo=timezone.get_current_timezone())
    return midnight - timedelta(days=DONE_WINDOW_DAYS)


def restrict_done(queryset, today: date | None = None):
    """Open tasks, and done tasks finished in the last 14 days."""
    cutoff = done_cutoff(today)
    return queryset.filter(
        Q(status__is_done=False)
        | Q(completed_at__gte=cutoff)
        | Q(completed_at__isnull=True, updated_at__gte=cutoff)
    )


def card_order():
    return [F("position").asc(), F("due_date").asc(nulls_last=True), "id"]


def column_value(mode: str, task: Task) -> str:
    """The key of the column a task sits in."""
    pk = {
        "status": task.status_id,
        "owner": task.owner_id,
        "category": task.category_id,
        "client": task.client_id,
        "section": task.section_id,
    }[mode]
    return str(pk) if pk is not None else "none"


def _empty_columns(mode: str, tasks: list[Task], project) -> list[Column]:
    if mode == "status":
        used = {t.status_id for t in tasks}
        return [
            Column(str(s.pk), s.name, s.colour)
            for s in TaskStatus.objects.all()
            if s.active or s.pk in used
        ]
    if mode == "owner":
        people = User.objects.staff().filter(is_active=True).order_by("name")
        return [Column("none", "Unassigned", "#94a3b8")] + [
            Column(str(u.pk), u.name, u.colour) for u in people
        ]
    if mode == "category":
        columns = [
            Column(str(c.pk), c.name, c.colour) for c in TaskCategory.objects.filter(active=True)
        ]
        known = {c.key for c in columns}
        for c in TaskCategory.objects.filter(pk__in={t.category_id for t in tasks} - {None}):
            if str(c.pk) not in known:
                columns.append(Column(str(c.pk), c.name, c.colour))
        return columns + [Column("none", "No category", "#94a3b8")]
    if mode == "client":
        ids = {t.client_id for t in tasks} - {None}
        clients = Client.objects.filter(pk__in=ids).order_by("name")
        return [Column(str(c.pk), c.name, "#64748b") for c in clients] + [
            Column("none", "No client", "#94a3b8")
        ]
    if mode == "section":
        sections = (
            ProjectSection.objects.filter(project=project)
            if project
            else ProjectSection.objects.none()
        )
        return [Column(str(s.pk), s.name, "#64748b") for s in sections] + [
            Column("none", "No section", "#94a3b8")
        ]
    return []


def build(queryset, mode: str, *, project=None, today: date | None = None) -> dict:
    """Columns of cards. Done work shows for 14 days only. A single query fetches the cards."""
    today = today or timezone.localdate()
    mode = valid_mode(mode, project=project is not None)
    rows = list(
        restrict_done(queryset, today)
        .select_related("client", "status", "owner", "category")
        .annotate(
            step_total=Count("steps", distinct=True),
            step_done=Count("steps", filter=Q(steps__done_at__isnull=False), distinct=True),
        )
        .order_by(*card_order())[:FETCH_LIMIT]
    )
    for task in rows:
        task.show_alert = task.alert(today)
        task.tone = task.deadline_tone(today)
        task.tone_icon = {"red": "exclamation-circle", "amber": "clock"}.get(task.tone, "")
    columns = _empty_columns(mode, rows, project)
    by_key = {c.key: c for c in columns}
    for task in rows:
        column = by_key.get(column_value(mode, task))
        if column is None:
            continue
        column.total += 1
        if len(column.tasks) < COLUMN_LIMIT:
            column.tasks.append(task)
    if mode == "status":
        for column in columns:
            status = next((s for s in TaskStatus.objects.all() if str(s.pk) == column.key), None)
            if status and status.is_done:
                column.note = f"Last {DONE_WINDOW_DAYS} days"
    # Empty "none" columns on owner/category/client boards stay: they are drop targets.
    return {
        "columns": columns,
        "mode": mode,
        "fetched": len(rows),
        "capped": len(rows) >= FETCH_LIMIT,
    }


def fetch_card(pk: int, today: date | None = None) -> Task:
    """One task with what a card shows."""
    today = today or timezone.localdate()
    task = (
        Task.objects.select_related("client", "status", "owner", "category")
        .annotate(
            step_total=Count("steps", distinct=True),
            step_done=Count("steps", filter=Q(steps__done_at__isnull=False), distinct=True),
        )
        .get(pk=pk)
    )
    task.tone = task.deadline_tone(today)
    task.tone_icon = {"red": "exclamation-circle", "amber": "clock"}.get(task.tone, "")
    return task
