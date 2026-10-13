"""Background jobs: draft reminders from schedules, and send approved messages."""

from datetime import time

from apps.jobs.registry import Daily, Every, register

from . import schedules, services


@register(
    "reminders",
    "Draft client reminders",
    Daily(time(6, 0)),
    description="Creates queued messages from the reminder schedules that are switched on. "
    "Safe to run twice.",
)
def reminders(run):
    return schedules.run_all()


@register(
    "send_messages",
    "Send approved messages",
    Every(5),
    description="Sends approved messages one at a time. Does nothing while sending is paused.",
)
def send_messages(run):
    return services.send_due()
