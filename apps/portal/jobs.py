from datetime import time

from apps.jobs.registry import Daily, register

from . import inforequest


@register(
    "info_reminders",
    "Information request reminders",
    Daily(time(9, 0)),
    description="Queues a reminder 7 and 14 days after an information request was emailed "
    "(held for approval), or tells the sender when a postal form has not come back.",
)
def info_reminders(run):
    return {"reminders": inforequest.send_reminders()}
