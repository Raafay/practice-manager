"""Notices and the daily email.

In-app notices are made where things happen (services.py) and by the deadline job here.
The daily email lists a person's overdue, due-today and due-this-week work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.core import dates
from apps.core.siteurl import absolute
from apps.services.models import Deadline

from .filters import week_bounds
from .models import Task, TaskStatus

DEADLINE_NOTICE_DAYS = 7


def deadline_notices(today: date | None = None) -> dict:
    """Tell the owner once when a deadline is within 7 days and the task is still To do."""
    today = today or timezone.localdate()
    limit = today + timedelta(days=DEADLINE_NOTICE_DAYS)
    default = TaskStatus.default()
    if default is None:
        return {"notified": 0}
    sent = 0
    tasks = (
        Task.objects.open()
        .filter(
            status=default, deadline__status=Deadline.Status.OPEN, deadline__due_date__lte=limit
        )
        .select_related("owner", "client", "deadline")
    )
    for task in tasks:
        owner = task.owner
        if owner is None or not (owner.is_active and owner.is_staff_kind):
            continue
        due = task.deadline.due_date
        when = "is overdue" if due < today else f"is due on {due:%d/%m/%Y}"
        notice = events.notify(
            owner,
            f"The deadline for {task.title} {when} and the task is still {default.name}.",
            reverse("tasks:detail", args=[task.pk]),
            kind="deadline",
            key=f"deadline-soon:{task.pk}:{due.isoformat()}",
        )
        if notice is not None:
            sent += 1
    return {"notified": sent}


@dataclass
class Digest:
    overdue: list = field(default_factory=list)
    today: list = field(default_factory=list)
    week: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.overdue or self.today or self.week)


def digest_for(user, today: date | None = None) -> Digest:
    """The user's open tasks by their target date, else their deadline. Honours their switches."""
    today = today or timezone.localdate()
    _, end_of_week = week_bounds(today)
    digest = Digest()
    tasks = (
        Task.objects.open()
        .filter(owner=user)
        .select_related("client", "status")
        .order_by("target_date", "due_date", "id")
    )
    for task in tasks:
        if task.status.is_waiting:
            continue
        when = task.target_date or task.due_date
        if when is None:
            continue
        if when < today:
            digest.overdue.append(task)
        elif when == today:
            digest.today.append(task)
        elif when <= end_of_week:
            digest.week.append(task)
    if not user.email_overdue:
        digest.overdue = []
    if not user.email_today:
        digest.today = []
    if not user.email_week:
        digest.week = []
    return digest


def _lines(title: str, tasks: list[Task]) -> list[str]:
    if not tasks:
        return []
    out = [f"{title} ({len(tasks)})"]
    for task in tasks:
        who = f" for {task.client.name}" if task.client_id else ""
        when = task.target_date or task.due_date
        out.append(f"  - {task.title}{who}, {when:%d/%m/%Y}")
        out.append(f"    {absolute(f'/tasks/{task.pk}/')}")
    return out + [""]


def daily_email_body(user, digest: Digest, practice: str = "") -> str:
    lines = [f"Good morning {user.name.split(' ')[0]},", ""]
    lines += _lines("Overdue", digest.overdue)
    lines += _lines("Due today", digest.today)
    lines += _lines("Due this week", digest.week)
    lines += [
        f"Your tasks: {absolute('/')}",
        "You can switch any of these emails off on your profile page.",
    ]
    return "\n".join(lines)


def send_daily_emails(today: date | None = None) -> dict:
    """The 08:00 email, on working days only. Nobody gets an empty email."""
    today = today or timezone.localdate()
    if not dates.is_working_day(today):
        return {"sent": 0, "skipped": "not a working day"}
    sent = 0
    for user in User.objects.staff().filter(is_active=True).exclude(email=""):
        digest = digest_for(user, today)
        if not digest:
            continue
        send_mail(
            f"Your tasks for {today:%d/%m/%Y}: {len(digest.overdue)} overdue, "
            f"{len(digest.today)} due today",
            daily_email_body(user, digest),
            None,
            [user.email],
        )
        sent += 1
    return {"sent": sent}
