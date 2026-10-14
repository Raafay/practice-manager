"""The monthly retention report. It lists and never deletes."""

from datetime import time

from django.urls import reverse

from apps import events
from apps.accounts.models import User
from apps.jobs.registry import Monthly, register

from . import retention


@register(
    "retention_report",
    "Retention report",
    Monthly(2, time(4, 0)),
    description="Lists clients, people and hidden documents whose retention dates have passed, "
    "and tells the owner. Nothing is deleted.",
)
def retention_report(run):
    report = retention.build_report()
    if report.total:
        for person in User.objects.staff().filter(is_active=True):
            if person.can("retention.manage"):
                events.notify(
                    person,
                    f"The retention report lists {report.total} item"
                    f"{'s' if report.total != 1 else ''} past their keep-until date.",
                    reverse("clients:retention"),
                    kind="retention",
                    key=f"retention:{report.today:%Y-%m}",
                )
    return report.counts()
