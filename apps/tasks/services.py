"""Business rules for tasks. Views call these; every change writes one event."""

from __future__ import annotations

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.clients.models import Client, Document
from apps.clients.services import store_document
from apps.core.html import clean_html
from apps.services import deadlines

from .models import (
    Task,
    TaskCategory,
    TaskComment,
    TaskDocument,
    TaskKind,
    TaskStar,
    TaskStatus,
    TaskStep,
)


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "no date"


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def task_url(task: Task) -> str:
    return reverse("tasks:detail", args=[task.pk])


def _record(actor, verb, summary, task, **data):
    return events.record(actor, verb, summary, client=task.client, target=task, **data)


def tell(user, actor, message: str, task: Task, kind: str):
    """A bell notice for `user` about `task`. Nobody is told about their own action."""
    if user is None or actor is None or user.pk == actor.pk:
        return None
    if not (user.is_active and user.is_staff_kind):
        return None
    return events.notify(user, message, task_url(task), kind=kind)


# ------------------------------------------------------------------ create


def create_task(
    actor,
    *,
    title: str,
    client: Client | None = None,
    kind: str = TaskKind.ADVISORY,
    category: TaskCategory | None = None,
    owner: User | None = None,
    status: TaskStatus | None = None,
    target_date: date | None = None,
    due_date: date | None = None,
    description: str = "",
    service=None,
    priority: str = Task.Priority.NORMAL,
    source: str = Task.Source.MANUAL,
    contact=None,
    project=None,
    section=None,
    repeating_task=None,
    start_date: date | None = None,
    estimate_minutes: int | None = None,
    period_label: str = "",
    notify: bool = True,
) -> Task:
    title = title.strip()
    if not title:
        raise ValidationError("Give the task a title.")
    if kind not in TaskKind.values:
        raise ValidationError("Choose what kind of work this is.")
    task = Task.objects.create(
        title=title[:250],
        description=clean_html(description),
        client=client,
        contact=contact,
        kind=kind,
        category=category,
        service=service,
        status=status or TaskStatus.default(),
        owner=owner,
        target_date=target_date,
        due_date=due_date,
        priority=priority,
        source=source,
        created_by=actor,
        project=project,
        section=section,
        repeating_task=repeating_task,
        start_date=start_date,
        estimate_minutes=estimate_minutes,
        period_label=period_label,
    )
    if owner is not None:
        task.followers.add(owner)
        if notify:
            tell(owner, actor, f"{who(actor)} assigned you {task.title}.", task, "assigned")
    _record(
        actor,
        "task.created",
        f"{who(actor)} created the task {task.title}"
        + (f" for {client.name}" if client else "")
        + (f", owned by {owner}" if owner else ", unassigned")
        + ".",
        task,
    )
    return task


# ------------------------------------------------------------------ fields

EDITABLE = {
    "title",
    "status",
    "owner",
    "reviewer",
    "team",
    "target_date",
    "due_date",
    "start_date",
    "priority",
    "kind",
    "category",
    "period_label",
    "estimate_minutes",
    "contact",
}


def _apply_status(task: Task, status: TaskStatus, actor) -> None:
    task.status = status
    if status.is_done:
        task.completed_at = timezone.now()
        task.completed_by = actor
    else:
        task.completed_at = None
        task.completed_by = None


def set_field(actor, task: Task, field: str, value) -> Task:
    """Change one field and write one event. A value equal to the old one writes nothing."""
    if field not in EDITABLE:
        raise ValidationError("That field cannot be changed.")
    if task.is_cancelled:
        raise ValidationError("A cancelled task cannot be changed.")
    old = getattr(task, field)
    if old == value:
        return task
    if field == "title":
        value = (value or "").strip()
        if not value:
            raise ValidationError("A task needs a title.")
        value = value[:250]
    if field == "status":
        if value is None:
            raise ValidationError("Choose a status.")
        _apply_status(task, value, actor)
    elif field == "owner" and value is not None and not (value.is_active and value.is_staff_kind):
        raise ValidationError("Choose someone who works here.")
    elif field in ("kind",) and value not in TaskKind.values:
        raise ValidationError("Choose what kind of work this is.")
    elif field == "priority" and value not in Task.Priority.values:
        raise ValidationError("Choose a priority.")
    else:
        setattr(task, field, value)
    task.save()
    if field == "owner" and value is not None:
        task.followers.add(value)
        tell(value, actor, f"{who(actor)} assigned you {task.title}.", task, "assigned")
    _record(
        actor,
        f"task.{field}_changed",
        _sentence(actor, task, field, old, value),
        task,
        old=_text(old),
        new=_text(getattr(task, field)),
    )
    return task


def _text(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _sentence(actor, task, field, old, new) -> str:
    name, person = task.title, who(actor)
    if field == "status":
        return f"{person} moved {name} to {task.status.name}."
    if field == "owner":
        return f"{person} assigned {name} to {new}." if new else f"{person} unassigned {name}."
    if field == "reviewer":
        return (
            f"{person} set {new} as reviewer of {name}."
            if new
            else f"{person} cleared the reviewer of {name}."
        )
    if field in ("target_date", "due_date", "start_date"):
        label = field.replace("_", " ")
        return f"{person} changed the {label} of {name} from {fmt(old)} to {fmt(new)}."
    if field == "title":
        return f"{person} renamed {old} to {new}."
    label = field.replace("_", " ")
    return f"{person} changed the {label} of {name} from {old or 'none'} to {new or 'none'}."


def complete(actor, task: Task) -> Task:
    done = TaskStatus.done_status()
    if done is None:
        raise ValidationError("There is no Done status. Add one in Settings.")
    return set_field(actor, task, "status", done)


def cancel(actor, task: Task) -> Task:
    if task.is_cancelled:
        return task
    task.cancelled_at = timezone.now()
    task.cancelled_by = actor
    task.save()
    _record(actor, "task.cancelled", f"{who(actor)} cancelled {task.title}.", task)
    return task


def set_description(actor, task: Task, html: str) -> Task:
    cleaned = clean_html(html)
    if cleaned == task.description:
        return task
    task.description = cleaned
    task.save(update_fields=["description", "updated_at"])
    _record(
        actor,
        "task.description_changed",
        f"{who(actor)} edited the description of {task.title}.",
        task,
    )
    return task


# ------------------------------------------------------------------ board and calendar moves

POSITION_GAP = 1024.0
BOARD_FIELDS = ("status", "owner", "category", "client", "section")


def _renumber(tasks) -> None:
    """Give a column's cards evenly spaced positions, in the order they show."""
    for index, task in enumerate(tasks, 1):
        value = index * POSITION_GAP
        if task.position != value:
            Task.objects.filter(pk=task.pk).update(position=value)
            task.position = value


def place(task: Task, column, before: Task | None, after: Task | None) -> None:
    """Put a card between two neighbours by changing only its own position.

    `before` is the card above it and `after` the card below, in the column as shown.
    When the neighbours have no room between them (all new cards share position 0), the
    column is renumbered once and the move is retried.
    """
    for attempt in (1, 2):
        low = before.position if before else None
        high = after.position if after else None
        if low is not None and high is not None:
            if high - low > 1e-6:
                value = (low + high) / 2
            elif attempt == 1:
                _renumber(list(column))
                before = next((t for t in column if t.pk == before.pk), before)
                after = next((t for t in column if t.pk == after.pk), after)
                continue
            else:
                value = high
        elif low is not None:
            value = low + POSITION_GAP
        elif high is not None:
            value = high - POSITION_GAP
        else:
            value = POSITION_GAP
        break
    Task.objects.filter(pk=task.pk).update(position=value, updated_at=timezone.now())
    task.position = value


def move_task(
    actor,
    task: Task,
    field: str,
    value,
    *,
    column=None,
    before: Task | None = None,
    after: Task | None = None,
) -> Task:
    """A drag on the board: change the column's field, then place the card.

    `value` is the new status, owner, category, client or section (None for the
    "none" column). One activity event is written, and none for a plain reorder.
    """
    if field not in BOARD_FIELDS:
        raise ValidationError("That column cannot be changed by dragging.")
    if task.is_cancelled:
        raise ValidationError("A cancelled task cannot be changed.")
    if field in ("status", "owner", "category"):
        if field == "status" and value is None:
            raise ValidationError("Choose a status.")
        set_field(actor, task, field, value)
    elif field == "client":
        if getattr(task, "client_id", None) != (value.pk if value else None):
            if task.deadline_id:
                raise ValidationError(
                    "This task comes from a deadline, so it stays with its client."
                )
            old = task.client
            task.client = value
            task.save(update_fields=["client", "updated_at"])
            events.record(
                actor,
                "task.client_changed",
                f"{who(actor)} moved {task.title} from {old.name if old else 'no client'} "
                f"to {value.name if value else 'no client'}.",
                client=value or old,
                target=task,
                old=old.name if old else "",
                new=value.name if value else "",
            )
    elif field == "section":
        if value is not None and value.project_id != task.project_id:
            raise ValidationError("That section belongs to a different project.")
        if task.section_id != (value.pk if value else None):
            old = task.section
            task.section = value
            task.save(update_fields=["section", "updated_at"])
            _record(
                actor,
                "task.section_changed",
                f"{who(actor)} moved {task.title} from {old or 'no section'} "
                f"to {value or 'no section'}.",
                task,
            )
    if column is not None:
        place(task, column, before, after)
    return task


def move_to_date(actor, task: Task, day: date | None) -> Task:
    """A drag on the calendar. Only the target date changes, never the due date."""
    return set_field(actor, task, "target_date", day)


# ------------------------------------------------------------------ steps


def toggle_step(actor, step: TaskStep, done: bool | None = None) -> TaskStep:
    """Tick or untick a step. Ticking the filing step marks the deadline done."""
    task = step.task
    if task.is_cancelled:
        raise ValidationError("A cancelled task cannot be changed.")
    ticking = (not step.is_done) if done is None else done
    if ticking == step.is_done:
        return step
    with transaction.atomic():
        step.done_at = timezone.now() if ticking else None
        step.done_by = actor if ticking else None
        step.save()
        _record(
            actor,
            "task.step_done" if ticking else "task.step_undone",
            f"{who(actor)} {'ticked' if ticking else 'unticked'} “{step.name}” on {task.title}.",
            task,
            step=step.name,
        )
        if ticking and step.is_filing and task.deadline_id:
            deadline = task.deadline
            if deadline.is_open:
                deadlines.mark_done(actor, deadline, evidence=f"Marked filed by {who(actor)}")
    if ticking:
        tell(
            task.owner,
            actor,
            f"{who(actor)} ticked “{step.name}” on {task.title}.",
            task,
            "step",
        )
    return step


def offer_to_complete(task: Task) -> bool:
    """A deadline was marked done elsewhere, so its open task gets a banner."""
    return bool(task.is_open and task.deadline_id and not task.deadline.is_open)


# ------------------------------------------------------------------ comments and followers

MENTION = re.compile(r"@([A-Za-z][\w'’.-]*(?: [A-Za-z][\w'’.-]*)?)")


def mentioned_users(body: str, *, exclude=None) -> list[User]:
    """People named after an @. A full name wins; a first name works if it is unique."""
    staff = list(User.objects.staff().filter(is_active=True))
    lowered = body.lower()
    found = {}
    for user in staff:
        if f"@{user.name.lower()}" in lowered:
            found[user.pk] = user
    first_names = {}
    for user in staff:
        first_names.setdefault(user.name.split(" ")[0].lower(), []).append(user)
    for match in MENTION.finditer(body):
        first = match.group(1).split(" ")[0].lower().rstrip(".-'’")
        people = first_names.get(first, [])
        if len(people) == 1:
            found[people[0].pk] = people[0]
    if exclude is not None:
        found.pop(exclude.pk, None)
    return list(found.values())


def add_comment(actor, task: Task, body: str) -> TaskComment:
    body = body.strip()
    if not body:
        raise ValidationError("Write a comment first.")
    comment = TaskComment.objects.create(task=task, author=actor, body=body[:5000])
    task.followers.add(actor)
    mentioned = mentioned_users(body, exclude=actor)
    already = {u.pk for u in mentioned}
    for user in mentioned:
        task.followers.add(user)
        events.notify(
            user, f"{who(actor)} mentioned you on {task.title}.", task_url(task), kind="mention"
        )
    for user in task.followers.filter(is_active=True).exclude(pk=actor.pk):
        if user.pk not in already:
            tell(user, actor, f"{who(actor)} commented on {task.title}.", task, "comment")
    _record(actor, "task.commented", f"{who(actor)} commented on {task.title}.", task)
    return comment


def toggle_follow(actor, task: Task) -> bool:
    if task.followers.filter(pk=actor.pk).exists():
        task.followers.remove(actor)
        return False
    task.followers.add(actor)
    return True


def toggle_star(actor, task: Task) -> bool:
    star, created = TaskStar.objects.get_or_create(task=task, user=actor)
    if not created:
        star.delete()
    return created


# ------------------------------------------------------------------ documents


def attach_upload(actor, task: Task, upload) -> TaskDocument:
    if task.client_id is None:
        raise ValidationError("Documents attach to a client's tasks. Choose a client first.")
    document = store_document(actor, task.client, upload, category=Document.Category.OTHER)
    return _link(actor, task, document)


def attach_document(actor, task: Task, document: Document) -> TaskDocument:
    if task.client_id is None or document.client_id != task.client_id:
        raise ValidationError("That document belongs to a different client.")
    return _link(actor, task, document)


def _link(actor, task, document) -> TaskDocument:
    link, created = TaskDocument.objects.get_or_create(
        task=task, document=document, defaults={"attached_by": actor}
    )
    if created:
        _record(
            actor,
            "task.document_attached",
            f"{who(actor)} attached {document.title} to {task.title}.",
            task,
        )
    return link


# ------------------------------------------------------------------ bulk

BULK_ACTIONS = ("owner", "status", "target_date", "complete", "cancel")


def bulk(actor, tasks, action: str, value=None) -> int:
    if action not in BULK_ACTIONS:
        raise ValidationError("Choose what to do with the ticked tasks.")
    changed = 0
    with transaction.atomic():
        for task in tasks:
            if task.is_cancelled:
                continue
            if action == "complete":
                complete(actor, task)
            elif action == "cancel":
                cancel(actor, task)
            else:
                set_field(actor, task, action, value)
            changed += 1
    return changed


# ------------------------------------------------------------------ settings


def can_delete_status(status: TaskStatus) -> bool:
    return not status.tasks.exists()


def can_delete_category(category: TaskCategory) -> bool:
    return not category.tasks.exists() and not category.templates.exists()


def merge_category(actor, source: TaskCategory, into: TaskCategory) -> int:
    if source.pk == into.pk:
        raise ValidationError("Choose a different category to merge into.")
    moved = source.tasks.update(category=into)
    source.templates.update(category=into)
    source.active = False
    source.save(update_fields=["active", "updated_at"])
    events.record(
        actor,
        "setting.changed",
        f"{who(actor)} merged the category “{source.name}” into “{into.name}” ({moved} tasks).",
        setting="task_category",
    )
    return moved


def merge_status(actor, source: TaskStatus, into: TaskStatus) -> int:
    if source.pk == into.pk:
        raise ValidationError("Choose a different status to merge into.")
    if source.is_done != into.is_done:
        raise ValidationError("Merge a done status only into another done status.")
    moved = source.tasks.update(status=into)
    source.active = False
    source.is_default = False
    source.save(update_fields=["active", "is_default", "updated_at"])
    events.record(
        actor,
        "setting.changed",
        f"{who(actor)} merged the status “{source.name}” into “{into.name}” ({moved} tasks).",
        setting="task_status",
    )
    return moved
