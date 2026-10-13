"""The nightly deadline job. Runs after the Companies House sync at 02:00."""

from datetime import time

from apps.jobs.registry import Daily, register

from . import deadlines


@register(
    "deadlines",
    "Deadline generation",
    Daily(time(3, 0)),
    description="Creates any deadline a live client's services should now have. Safe to run twice.",
)
def nightly_deadlines(run):
    return deadlines.generate_all()
