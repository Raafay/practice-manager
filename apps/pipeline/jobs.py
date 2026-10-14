"""Background jobs: quiet prospects and expired proposals."""

from datetime import time

from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.jobs.registry import Daily, register

from . import proposals, services


def notify_quiet(today=None) -> int:
    """Tell each prospect's owner once per quiet spell. The key ties the notice to the spell."""
    today = today or timezone.localdate()
    count = 0
    for details in services.quiet_prospects(today=today):
        if details.owner is None or not details.owner.is_active:
            continue
        anchor = details.next_action_date
        if anchor is None or anchor >= today:
            activity = services.last_activity(details)
            anchor = timezone.localtime(activity).date() if activity else today
        reason = services.quiet_reason(details, today).lower()
        note = events.notify(
            details.owner,
            f"{details.client.name} has gone quiet: {reason}.",
            reverse("clients:detail", args=[details.client_id]),
            kind="quiet_prospect",
            key=f"quiet-{details.pk}-{anchor.isoformat()}",
        )
        count += 1 if note is not None else 0
    return count


@register(
    "pipeline_daily",
    "Quiet prospects and expired proposals",
    Daily(time(6, 50)),
    description="Tells a prospect's owner once when it goes quiet, and marks proposals past "
    "their valid-until date as expired. Safe to run twice.",
)
def pipeline_daily(run):
    return {"quiet_notices": notify_quiet(), "expired": proposals.expire_overdue()}
