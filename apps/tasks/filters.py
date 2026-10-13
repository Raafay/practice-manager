"""Reading the Tasks page's address: chips, filters, sort and grouping.

The whole view state lives in the query string so a view can be bookmarked,
saved and shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from django import forms
from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Lower
from django.http import QueryDict
from django.utils import timezone

from apps.accounts.models import Team, User
from apps.core.forms import DateInput, StyledFormMixin
from apps.services.models import Service

from .models import Task, TaskCategory, TaskKind, TaskStar, TaskStatus

CHIPS = [
    ("all", "All"),
    ("compliance", "Compliance"),
    ("fractional", "Fractional"),
    ("requests", "Requests"),
    ("mine", "Mine"),
    ("unassigned", "Unassigned"),
    ("overdue", "Overdue"),
    ("this_week", "This week"),
]
CHIP_KEYS = {key for key, _ in CHIPS}

GROUPS = [
    ("", "No grouping"),
    ("client", "Client"),
    ("owner", "Owner"),
    ("status", "Status"),
    ("category", "Category"),
    ("service", "Service"),
    ("week", "Week due"),
]
GROUP_KEYS = {key for key, _ in GROUPS if key}

# Column key -> order-by expressions. Empty dates always sort last.
SORTS = {
    "deadline": [F("due_date").asc(nulls_last=True), F("target_date").asc(nulls_last=True)],
    "name": [Lower("title")],
    "client": [Lower("client__name")],
    "category": [F("category__name").asc(nulls_last=True)],
    "owner": [F("owner__name").asc(nulls_last=True)],
    "status": [F("status__position")],
    "target": [F("target_date").asc(nulls_last=True), F("due_date").asc(nulls_last=True)],
}
DESCENDING = {
    "deadline": [F("due_date").desc(nulls_last=True), F("target_date").desc(nulls_last=True)],
    "name": [Lower("title").desc()],
    "client": [Lower("client__name").desc()],
    "category": [F("category__name").desc(nulls_last=True)],
    "owner": [F("owner__name").desc(nulls_last=True)],
    "status": [F("status__position").desc()],
    "target": [F("target_date").desc(nulls_last=True), F("due_date").desc(nulls_last=True)],
}
DEFAULT_SORT = "deadline"

PER_GROUP = 50
IN_ALL = 200


def valid_sort(value: str) -> str:
    key = (value or "").lstrip("-")
    return value if key in SORTS else ""


def ordering_for(sort: str) -> list:
    sort = valid_sort(sort) or DEFAULT_SORT
    table = DESCENDING if sort.startswith("-") else SORTS
    return [*table[sort.lstrip("-")], "id"]


def week_bounds(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


class TaskFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search")
    owner = forms.ChoiceField(required=False, label="Owner")
    client = forms.CharField(required=False, label="Client", help_text="A name or number.")
    manager = forms.ModelChoiceField(
        User.objects.none(), required=False, empty_label="Anyone", label="Client manager"
    )
    team = forms.ModelChoiceField(Team.objects.none(), required=False, empty_label="Any team")
    kind = forms.ChoiceField(
        required=False, choices=[("", "Any kind"), *TaskKind.choices], label="Kind"
    )
    category = forms.ModelChoiceField(
        TaskCategory.objects.none(), required=False, empty_label="Any category"
    )
    service = forms.ModelChoiceField(
        Service.objects.none(), required=False, empty_label="Any service"
    )
    status = forms.ModelChoiceField(
        TaskStatus.objects.none(), required=False, empty_label="Any status"
    )
    priority = forms.ChoiceField(
        required=False, choices=[("", "Any priority"), *Task.Priority.choices]
    )
    project = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)
    starred = forms.BooleanField(required=False, label="Starred only")
    date_field = forms.ChoiceField(
        required=False,
        choices=[("target", "Target date"), ("due", "Deadline")],
        label="Date range on",
    )
    date_from = forms.DateField(required=False, widget=DateInput, label="From")
    date_to = forms.DateField(required=False, widget=DateInput, label="To")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        people = User.objects.staff().filter(is_active=True)
        self.fields["owner"].choices = [
            ("", "Anyone"),
            ("none", "Unassigned"),
            *[(str(u.pk), u.name) for u in people],
        ]
        self.fields["manager"].queryset = people
        self.fields["team"].queryset = Team.objects.all()
        self.fields["category"].queryset = TaskCategory.objects.filter(active=True)
        self.fields["service"].queryset = Service.objects.all()
        self.fields["status"].queryset = TaskStatus.objects.filter(active=True)

    def values(self) -> dict:
        """Only the fields that are valid; a bad value is ignored, never an error page."""
        self.is_valid()
        return {k: v for k, v in self.cleaned_data.items() if v not in (None, "", False)}


@dataclass
class TaskQuery:
    chip: str
    show_done: bool
    group: str
    sort: str
    values: dict

    @property
    def filters_active(self) -> bool:
        return bool(self.values)


FILTER_KEYS = list(TaskFilterForm.base_fields)
STATE_KEYS = ["chip", "show_done", "group", "sort"]


def parse(params: QueryDict) -> tuple[TaskQuery, TaskFilterForm]:
    form = TaskFilterForm(params)
    chip = params.get("chip", "all")
    group = params.get("group", "")
    return (
        TaskQuery(
            chip=chip if chip in CHIP_KEYS else "all",
            show_done=params.get("show_done") in ("1", "on", "true"),
            group=group if group in GROUP_KEYS else "",
            sort=valid_sort(params.get("sort", "")),
            values=form.values(),
        ),
        form,
    )


def apply(query: TaskQuery, user, *, today: date | None = None, client=None):
    """The tasks for a query, with a starred flag for this user. Cancelled tasks never show."""
    today = today or timezone.localdate()
    tasks = Task.objects.live().annotate(
        is_starred=Exists(TaskStar.objects.filter(task=OuterRef("pk"), user=user))
    )
    if client is not None:
        tasks = tasks.filter(client=client)
    if not query.show_done:
        tasks = tasks.filter(status__is_done=False)
    tasks = _chip(tasks, query.chip, user, today)
    return _filters(tasks, query.values, user)


def _chip(tasks, chip: str, user, today: date):
    if chip == "compliance":
        return tasks.filter(kind=TaskKind.COMPLIANCE)
    if chip == "fractional":
        return tasks.filter(kind=TaskKind.ADVISORY)
    if chip == "requests":
        return tasks.filter(kind=TaskKind.REQUEST)
    if chip == "mine":
        return tasks.filter(owner=user)
    if chip == "unassigned":
        return tasks.filter(owner__isnull=True)
    if chip == "overdue":
        return tasks.filter(status__is_done=False).filter(
            Q(target_date__lt=today) | Q(due_date__lt=today)
        )
    if chip == "this_week":
        first, last = week_bounds(today)
        return tasks.filter(Q(target_date__range=(first, last)) | Q(due_date__range=(first, last)))
    return tasks


def _filters(tasks, values: dict, user):
    owner = values.get("owner")
    if owner == "none":
        tasks = tasks.filter(owner__isnull=True)
    elif owner:
        tasks = tasks.filter(owner_id=owner)
    client = values.get("client")
    if client:
        if client.isdigit():
            tasks = tasks.filter(client_id=int(client))
        else:
            tasks = tasks.filter(
                Q(client__name__icontains=client) | Q(client__reference__iexact=client)
            )
    if values.get("manager"):
        tasks = tasks.filter(client__manager=values["manager"])
    for name in ("team", "category", "service", "status"):
        if values.get(name):
            tasks = tasks.filter(**{name: values[name]})
    for name in ("kind", "priority"):
        if values.get(name):
            tasks = tasks.filter(**{name: values[name]})
    if values.get("project"):
        tasks = tasks.filter(project_id=values["project"])
    if values.get("starred"):
        tasks = tasks.filter(is_starred=True)
    column = "due_date" if values.get("date_field") == "due" else "target_date"
    if values.get("date_from"):
        tasks = tasks.filter(**{f"{column}__gte": values["date_from"]})
    if values.get("date_to"):
        tasks = tasks.filter(**{f"{column}__lte": values["date_to"]})
    if values.get("q"):
        for word in values["q"].split():
            tasks = tasks.filter(
                Q(title__icontains=word)
                | Q(client__name__icontains=word)
                | Q(period_label__icontains=word)
            )
    return tasks


def query_string(params: QueryDict, **changes) -> str:
    """The current state as a query string, with changes. An empty value removes a key."""
    pairs = []
    skip = set(changes) | {"page", "view"}
    for key in params:
        if key in skip:
            continue
        pairs += [(key, v) for v in params.getlist(key) if v != ""]
    for key, value in changes.items():
        if value not in (None, "", False):
            pairs.append((key, value))
    return urlencode(pairs)


def state_query(query: TaskQuery, params: QueryDict) -> str:
    """The query string to save in a view: filters, chip, grouping and sort, no paging."""
    pairs = []
    for key in [*FILTER_KEYS, *STATE_KEYS]:
        pairs += [(key, v) for v in params.getlist(key) if v != ""]
    return urlencode(pairs)
