"""Turning deadlines into tasks (docs/specs/04-tasks.md section 3).

`create_for_deadline` is safe to run twice: a task is unique on deadline and template.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.dates import add_working_days, ct_payment_due, previous_working_day
from apps.services.models import Deadline

from .models import Task, TaskKind, TaskStatus, TaskStep, TaskTemplate


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def task_name(template: TaskTemplate, deadline: Deadline) -> str:
    """The name pattern filled in. Dates print as dd/mm/yyyy."""
    return template.name_pattern.format(
        period_end=fmt(deadline.period_end or deadline.due_date),
        period_label=deadline.label,
        due_date=fmt(deadline.due_date),
    )[:250]


def target_date_for(template: TaskTemplate, deadline: Deadline) -> date:
    """When the practice plans to finish. Always a working day."""
    due = deadline.due_date
    kind = template.target_kind
    if kind == TaskTemplate.Target.WORKING_DAYS_BEFORE_DUE:
        return add_working_days(due, -template.target_days)
    if kind == TaskTemplate.Target.DAYS_BEFORE_CT_PAYMENT:
        base = ct_payment_due(deadline.period_end) if deadline.period_end else due
        target = base - timedelta(days=template.target_days)
    elif kind == TaskTemplate.Target.FIXED_DAY:
        year = due.year
        target = date(year, template.target_month, template.target_day)
        if target >= due:
            target = date(year - 1, template.target_month, template.target_day)
    else:
        target = due - timedelta(days=template.target_days)
    return previous_working_day(target)


def default_owner(template: TaskTemplate, client: Client) -> User | None:
    """Manager, then partner, then an owner (CORRECTIONS 19)."""
    choice = template.default_owner
    if choice == TaskTemplate.Owner.NOBODY:
        return None
    if choice == TaskTemplate.Owner.USER:
        user = template.owner_user
        return user if user and user.is_active else None
    order = (
        [client.manager, client.partner]
        if choice == TaskTemplate.Owner.MANAGER
        else [client.partner, client.manager]
    )
    for user in order:
        if user is not None and user.is_active:
            return user
    return User.objects.active_owners().order_by("pk").first()


def _wanted(deadline: Deadline) -> bool:
    client = deadline.client
    return (
        deadline.is_open
        and deadline.client_service_id is not None
        and client.status == Client.Status.ACTIVE
        and client.archived_at is None
    )


def _templates_by_key() -> dict[tuple[int, str], list[TaskTemplate]]:
    table = defaultdict(list)
    templates = TaskTemplate.objects.filter(active=True).select_related("category", "owner_user")
    for template in templates.prefetch_related("steps"):
        table[(template.service_id, template.rule)].append(template)
    return table


def create_for_deadline(deadline: Deadline, *, templates=None, actor=None) -> list[Task]:
    """One task for each active template of the deadline's service and rule."""
    if not _wanted(deadline):
        return []
    table = templates if templates is not None else _templates_by_key()
    service_id = deadline.client_service.service_id
    made = []
    status = TaskStatus.default()
    existing = set(deadline.tasks.values_list("template_id", flat=True))
    for template in table.get((service_id, deadline.rule), []):
        if template.pk in existing:
            continue
        try:
            with transaction.atomic():
                task = Task.objects.create(
                    title=task_name(template, deadline),
                    client=deadline.client,
                    kind=TaskKind.COMPLIANCE,
                    category=template.category,
                    service_id=service_id,
                    deadline=deadline,
                    template=template,
                    status=status,
                    owner=default_owner(template, deadline.client),
                    due_date=deadline.due_date,
                    target_date=target_date_for(template, deadline),
                    period_label=deadline.label,
                    estimate_minutes=template.estimate_minutes,
                    source=Task.Source.GENERATED,
                )
                TaskStep.objects.bulk_create(
                    TaskStep(
                        task=task,
                        name=step.name,
                        position=step.position,
                        stops_reminders=step.stops_reminders,
                        is_filing=step.is_filing,
                    )
                    for step in template.steps.all()
                )
        except IntegrityError:
            continue  # another run made it first
        made.append(task)
    return made


def create_for_deadlines(deadlines, *, actor=None) -> list[Task]:
    table = _templates_by_key()
    made = []
    for deadline in deadlines:
        made += create_for_deadline(deadline, templates=table, actor=actor)
    by_client = defaultdict(list)
    for task in made:
        by_client[task.client].append(task)
    for client, tasks in by_client.items():
        events.record(
            actor,
            "task.generated",
            f"{len(tasks)} task{'s' if len(tasks) != 1 else ''} created for {client.name}.",
            client=client,
            titles=[t.title for t in tasks][:20],
        )
    return made


def sync_due_dates(deadline: Deadline, old: date | None, new: date, *, actor=None) -> int:
    """The task's due date follows the deadline. Done and cancelled tasks are left alone."""
    count = 0
    for task in deadline.tasks.live().filter(status__is_done=False).exclude(due_date=new):
        before = task.due_date
        task.due_date = new
        task.save(update_fields=["due_date", "updated_at"])
        events.record(
            actor,
            "task.due_changed",
            f"Due date of {task.title} moved from {fmt(before)} to {fmt(new)} with its deadline.",
            client=task.client,
            target=task,
            old=before,
            new=new,
        )
        count += 1
    return count


def catch_up(*, today: date | None = None) -> dict:
    """Make any missing tasks for open deadlines and bring due dates into line."""
    today = today or timezone.localdate()
    table = _templates_by_key()
    counts = {"deadlines": 0, "created": 0, "dates_moved": 0}
    deadlines = (
        Deadline.objects.open()
        .filter(
            client__status=Client.Status.ACTIVE,
            client__archived_at__isnull=True,
            client_service__isnull=False,
        )
        .select_related("client__manager", "client__partner", "client_service")
        .order_by("pk")
    )
    for deadline in deadlines:
        counts["deadlines"] += 1
        counts["created"] += len(create_for_deadline(deadline, templates=table))
    drifted = Task.objects.open().filter(deadline__isnull=False).select_related("deadline")
    for task in drifted:
        if task.deadline.is_open and task.due_date != task.deadline.due_date:
            counts["dates_moved"] += sync_due_dates(
                task.deadline, task.due_date, task.deadline.due_date
            )
    return counts
