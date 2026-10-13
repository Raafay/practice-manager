"""Building the table: groups, limits and rows, in a bounded number of queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlencode

from django.utils import timezone

from .filters import IN_ALL, PER_GROUP, TaskQuery, ordering_for
from .models import Task

ROW_FIELDS = (
    "id",
    "client_id",
    "client__name",
    "owner_id",
    "owner__name",
    "status_id",
    "status__name",
    "status__position",
    "category_id",
    "category__name",
    "service_id",
    "service__name",
    "due_date",
    "target_date",
)


@dataclass
class Group:
    key: str
    label: str
    sort_key: tuple
    ids: list[int] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    picked: list[int] = field(default_factory=list)
    prefill: dict = field(default_factory=dict)
    add_url: str = ""

    @property
    def total(self) -> int:
        return len(self.ids)

    @property
    def hidden(self) -> int:
        return self.total - len(self.tasks)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _group_for(row: dict, mode: str) -> tuple[str, str, tuple, dict]:
    """(key, label, ordering, values for an Add task row) for one task row."""
    if mode == "client":
        if row["client_id"] is None:
            return "none", "No client", (1, ""), {}
        return (
            str(row["client_id"]),
            row["client__name"],
            (0, row["client__name"].lower()),
            {"client": row["client_id"]},
        )
    if mode == "owner":
        if row["owner_id"] is None:
            return "none", "Unassigned", (1, ""), {}
        return (
            str(row["owner_id"]),
            row["owner__name"],
            (0, row["owner__name"].lower()),
            {"owner": row["owner_id"]},
        )
    if mode == "status":
        return (
            str(row["status_id"]),
            row["status__name"],
            (0, row["status__position"]),
            {"status": row["status_id"]},
        )
    if mode == "category":
        if row["category_id"] is None:
            return "none", "No category", (1, ""), {}
        return (
            str(row["category_id"]),
            row["category__name"],
            (0, row["category__name"].lower()),
            {"category": row["category_id"]},
        )
    if mode == "service":
        if row["service_id"] is None:
            return "none", "No service", (1, ""), {}
        return (
            str(row["service_id"]),
            row["service__name"],
            (0, row["service__name"].lower()),
            {"service": row["service_id"]},
        )
    if mode == "week":
        when = row["due_date"] or row["target_date"]
        if when is None:
            return "none", "No date", (1, ""), {}
        start = _week_start(when)
        return (
            start.isoformat(),
            f"Week of {start:%d/%m/%Y}",
            (0, start.isoformat()),
            {"target_date": start.isoformat()},
        )
    return "all", "", (0, ""), {}


def decorate(tasks: list[Task], today: date) -> list[Task]:
    for task in tasks:
        task.show_alert = task.alert(today)
        task.tone = task.deadline_tone(today)
        task.tone_icon = {"red": "exclamation-circle", "amber": "clock"}.get(task.tone, "")
        task.latest = task.latest_action
        task.step_list = list(task.steps.all())
    return tasks


def build(
    queryset,
    query: TaskQuery,
    *,
    page: int = 1,
    today: date | None = None,
    new_url: str = "",
    client_id: int | None = None,
) -> dict:
    """The groups to show for a query. Two queries for rows, one for steps."""
    today = today or timezone.localdate()
    page = max(page, 1)
    ordered = queryset.order_by(*ordering_for(query.sort))
    rows = ordered.values(*ROW_FIELDS)

    groups: dict[str, Group] = {}
    for row in rows:
        key, label, order, prefill = _group_for(row, query.group)
        group = groups.get(key)
        if group is None:
            group = groups[key] = Group(key, label, order, prefill=prefill)
        group.ids.append(row["id"])

    ordered_groups = (
        sorted(groups.values(), key=lambda g: g.sort_key) if query.group else list(groups.values())
    )
    per_group = PER_GROUP * page if query.group else IN_ALL * page
    remaining = IN_ALL * page
    chosen: list[int] = []
    for group in ordered_groups:
        take = max(min(per_group, remaining, group.total), 0)
        picked = group.ids[:take]
        remaining -= take
        chosen += picked
        group.picked = picked

    fetched = {
        t.pk: t
        for t in queryset.filter(pk__in=chosen)
        .order_by()
        .select_related("client", "status", "owner", "category")
        .prefetch_related("steps")
    }
    for group in ordered_groups:
        group.tasks = decorate([fetched[i] for i in group.picked if i in fetched], today)
        prefill = dict(group.prefill)
        if client_id is not None:
            prefill["client"] = client_id
        group.add_url = f"{new_url}?{urlencode(prefill)}" if prefill else new_url
    return {
        "groups": ordered_groups,
        "total": sum(g.total for g in ordered_groups),
        "more": any(g.hidden > 0 for g in ordered_groups),
        "next_page": page + 1,
        "add_url_all": f"{new_url}?client={client_id}" if client_id is not None else new_url,
    }
