"""What Settings, System shows the owner: is everything working? (Stage 13, item 9)."""

import os
import platform
from datetime import timedelta

import django
from django.conf import settings
from django.utils import timezone

# The worker writes a heartbeat each minute; older than this means it has stopped.
WORKER_STALE_AFTER = timedelta(minutes=5)
PROVIDER_LABELS = {
    "ses": "Amazon SES",
    "postmark": "Postmark",
    "brevo": "Brevo",
    "console": "None (development: printed, not sent)",
}


def jobs_status(now=None) -> dict:
    from apps.jobs import registry, services
    from apps.jobs.models import JobRun

    now = now or timezone.now()
    last = services.last_runs()
    rows = []
    for job in registry.all_jobs():
        run = last.get(job.name)
        rows.append({"job": job, "last": run, "failed": run is not None and run.state == "failed"})
    seen = services.worker_last_seen()
    failures = JobRun.objects.filter(state="failed", started_at__gte=now - timedelta(days=7))
    worker_ok = seen is not None and now - seen <= WORKER_STALE_AFTER
    return {
        "rows": rows,
        "worker_seen": seen,
        "worker_ok": worker_ok,
        "failed_week": failures.count(),
        "ok": worker_ok and not any(row["failed"] for row in rows),
    }


def email_status(now=None) -> dict:
    from apps.comms import services as comms
    from apps.comms.models import QueuedMessage

    now = now or timezone.now()
    week = now - timedelta(days=7)
    messages = QueuedMessage.objects
    failed = messages.filter(state="failed").count()
    bounced = comms.recent_delivery_problems()
    provider = getattr(settings, "EMAIL_PROVIDER", "console")
    return {
        "provider": PROVIDER_LABELS.get(provider, provider),
        "from_address": comms.sending_address(),
        "paused": comms.is_paused(),
        "sent_week": messages.filter(state="sent", sent_at__gte=week).count(),
        "waiting": comms.pending_count(),
        "failed": failed,
        "bounced": bounced,
        "ok": not failed and not bounced and provider != "console",
    }


def integrations_status(user) -> dict:
    from apps.companieshouse import api
    from apps.finance import sync
    from apps.jobs.models import JobRun

    xero = sync.status() if user.can("finance.owner") else None
    return {
        "ch_key": api.key_present(),
        "ch_last": JobRun.objects.filter(name="ch_sync").first(),
        "xero": xero,
    }


def version() -> dict:
    module = (settings.SETTINGS_MODULE or os.environ.get("DJANGO_SETTINGS_MODULE", "")).rsplit(
        ".", 1
    )[-1]
    return {
        "app": settings.APP_VERSION,
        "settings": module,
        "python": platform.python_version(),
        "django": django.get_version(),
    }
