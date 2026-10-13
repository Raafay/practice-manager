"""Reminder schedules: drafting queued messages from deadlines and tasks.

The job calls `run_all`. Every message has a duplicate key such as
`schedule:12:deadline:345:repeat:2`, so running it twice makes nothing twice.
"""

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.dates import add_working_days
from apps.services.models import Deadline

from . import services
from .models import Channel, MessageTemplate, QueuedMessage, ReminderSchedule

# How far back a missed date is still sent. A job that did not run for longer
# than this skips the missed dates rather than flooding clients.
CATCH_UP_DAYS = 3


def fire_dates(schedule: ReminderSchedule, base: date) -> list[date]:
    """Every date this schedule fires for a deadline, in order.

    Each offset gives a first date; then, if the schedule repeats, one more every
    `repeat_every_days` for up to `max_repeats` times.
    """
    first: list[date] = []
    for offset in sorted(
        {int(o) for o in schedule.offsets}, reverse=schedule.trigger == "before_deadline"
    ):
        if schedule.trigger in ("before_deadline", "before_target"):
            if schedule.working_days:
                first.append(add_working_days(base, -offset))
            else:
                first.append(base - timedelta(days=offset))
        else:
            if schedule.working_days:
                first.append(add_working_days(base, offset))
            else:
                first.append(base + timedelta(days=offset))
    dates = list(first)
    if schedule.repeat_every_days and schedule.max_repeats:
        start = first[0] if first else base
        for n in range(1, schedule.max_repeats + 1):
            dates.append(start + timedelta(days=schedule.repeat_every_days * n))
    return sorted(set(dates))


def _stopped(deadline: Deadline | None, task) -> bool:
    """A step flagged "stops reminders" has been ticked on a related task."""
    from apps.tasks.models import TaskStep

    steps = TaskStep.objects.filter(stops_reminders=True, done_at__isnull=False)
    if task is not None:
        return steps.filter(task=task).exists()
    if deadline is not None:
        return steps.filter(task__deadline=deadline).exists()
    return False


def _make(schedule, client, *, key, reason, deadline=None, task=None):
    template = schedule.template
    if not template.active:
        return None
    recipients = services.reminder_recipients(client, main_only=schedule.to_main_only)
    if schedule.template.channel == Channel.SMS:
        numbers = [c.mobile for c in recipients if c.mobile] or []
        to = ", ".join(numbers)
    else:
        to = ", ".join(c.email for c in recipients)
    contact = recipients[0] if recipients else services.main_contact(client)
    ctx = services.build_context(client, contact=contact, deadline=deadline, task=task)
    ctx.user = client.manager or client.partner
    subject, html, text, problems = services.render_template(template, ctx)
    automatic = template.send_mode == MessageTemplate.SendMode.AUTO
    state = QueuedMessage.State.NEEDS_APPROVAL
    message = services.create_message(
        client,
        template=template,
        to=to,
        subject=subject,
        body_html=html if template.channel != Channel.SMS else "",
        body_text=text,
        channel=template.channel,
        state=state,
        reason=reason,
        contact=contact,
        task=task,
        deadline=deadline,
        duplicate_key=key,
    )
    # Automatic sending only when the owner said so for this template and nothing
    # is wrong with the message. Anything else waits for a person.
    if (
        automatic
        and message.state == QueuedMessage.State.NEEDS_APPROVAL
        and not problems
        and not services.approval_problems(message)
        and not services.skip_reason(client, automatic=True)
    ):
        message.state = QueuedMessage.State.APPROVED
        message.approved_at = timezone.now()
        message.send_after = message.approved_at
        message.reason = f"{message.reason} (sent automatically: the template is set to automatic)"[
            :300
        ]
        message.save()
    return message


def run_schedule(schedule: ReminderSchedule, today: date | None = None) -> int:
    """Create the messages that are due today for one schedule. Returns how many were made."""
    today = today or timezone.localdate()
    if not schedule.active:
        return 0
    made = 0
    if schedule.trigger in ("before_deadline", "after_period_end"):
        deadlines = Deadline.objects.filter(
            rule=schedule.rule, status=Deadline.Status.OPEN
        ).select_related("client", "client__manager", "client__partner", "client_service")
        for deadline in deadlines:
            base = (
                deadline.due_date if schedule.trigger == "before_deadline" else deadline.period_end
            )
            if base is None:
                continue
            made += _schedule_dates(schedule, deadline.client, base, today, deadline=deadline)
    else:
        made += _run_task_based(schedule, today)
    return made


def _schedule_dates(schedule, client, base, today, *, deadline=None, task=None) -> int:
    if services.skip_reason(client, automatic=True):
        return 0
    if _stopped(deadline, task):
        return 0
    made = 0
    for index, when in enumerate(fire_dates(schedule, base)):
        if not (today - timedelta(days=CATCH_UP_DAYS) <= when <= today):
            continue
        subject = f"deadline:{deadline.pk}" if deadline else f"task:{task.pk}"
        key = f"schedule:{schedule.pk}:{subject}:repeat:{index}"
        if QueuedMessage.objects.filter(duplicate_key=key).exists():
            continue
        what = deadline.label if deadline else task.title
        reason = f"{schedule.name}: {what}, due {base:%d/%m/%Y}."
        with transaction.atomic():
            if _make(schedule, client, key=key, reason=reason, deadline=deadline, task=task):
                made += 1
    return made


def _run_task_based(schedule, today) -> int:
    from apps.tasks.models import Task, TaskStep

    if schedule.task_template_id is None:
        return 0  # without a task template there is nothing to match
    tasks = Task.objects.filter(
        template=schedule.task_template, client__isnull=False, cancelled_at__isnull=True
    ).select_related("client", "client__manager", "client__partner", "status", "deadline")
    made = 0
    for task in tasks.exclude(status__is_done=True):
        if schedule.trigger == "before_target":
            if task.target_date is None:
                continue
            made += _schedule_dates(schedule, task.client, task.target_date, today, task=task)
        elif schedule.trigger == "step_ticked":
            step = TaskStep.objects.filter(
                task=task, name__iexact=schedule.step_name, done_at__isnull=False
            ).first()
            if step is None:
                continue
            key = f"schedule:{schedule.pk}:task:{task.pk}:repeat:0"
            if QueuedMessage.objects.filter(duplicate_key=key).exists():
                continue
            if services.skip_reason(task.client, automatic=True):
                continue
            reason = f"{schedule.name}: “{step.name}” was ticked on {task.title}."
            if _make(schedule, task.client, key=key, reason=reason, task=task):
                made += 1
    return made


def run_all(today: date | None = None) -> dict:
    made = 0
    for schedule in ReminderSchedule.objects.filter(active=True).select_related("template"):
        made += run_schedule(schedule, today)
    return {"created": made}
