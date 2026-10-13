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
