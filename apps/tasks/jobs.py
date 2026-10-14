"""The catch-up job: makes any task a deadline should have, and fixes drifted due dates."""

from datetime import time

from apps.jobs.registry import Daily, register

from . import generation


@register(
    "tasks_catch_up",
    "Task catch-up",
    Daily(time(3, 30)),
    description="Creates any task an open deadline should have and keeps due dates in step. "
    "Safe to run twice.",
)
def tasks_catch_up(run):
    return generation.catch_up()


@register(
    "repeating_tasks",
    "Repeating tasks",
    Daily(time(3, 45)),
    description="Makes the task for the current period of each repeating task. Safe to run twice.",
)
def repeating_tasks(run):
    from . import repeating

    return repeating.create_due()


@register(
    "task_notices",
    "Deadline notices",
    Daily(time(7, 0)),
    description="Tells a task's owner once when its deadline is within 7 days and it is "
    "still To do.",
)
def task_notices(run):
    from . import notices

    return notices.deadline_notices()


@register(
    "daily_task_email",
    "Daily task email",
    Daily(time(8, 0)),
    description="Emails each person their overdue, due-today and due-this-week tasks. "
    "Working days only. People can switch each part off on their profile.",
)
def daily_task_email(run):
    from . import notices

    return notices.send_daily_emails()
