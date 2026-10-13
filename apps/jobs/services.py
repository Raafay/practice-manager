"""Running jobs: the lock, the run log, what is due, and the failure notice."""

import logging
import socket
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps import events

from . import registry
from .models import JobLock, JobRun, WorkerHeartbeat

logger = logging.getLogger(__name__)

# A lock older than this is taken to belong to a worker that died mid-run.
STALE_LOCK = timedelta(hours=3)


def _claim(name: str, now: datetime) -> bool:
    """Take the job's lock. False if another worker holds it.

    One conditional UPDATE: PostgreSQL locks the row, so only one caller can win.
    """
    JobLock.objects.get_or_create(name=name)
    claimed = JobLock.objects.filter(
        Q(running_since__isnull=True) | Q(running_since__lt=now - STALE_LOCK), name=name
    ).update(running_since=now, requested_at=None, requested_by=None, updated_at=now)
    return claimed == 1


def _release(name: str) -> None:
    JobLock.objects.filter(name=name).update(running_since=None, updated_at=timezone.now())


def is_running(name: str) -> bool:
    return JobLock.objects.filter(name=name, running_since__isnull=False).exists()


def run_job(
    name: str,
    *,
    trigger: str = JobRun.Trigger.COMMAND,
    user=None,
    slot: datetime | None = None,
    now: datetime | None = None,
) -> JobRun | None:
    """Run one job now. Returns None, and runs nothing, if it is already running."""
    job = registry.get(name)
    now = now or timezone.now()
    if not _claim(name, now):
        return None
    run = JobRun.objects.create(
        name=name, started_at=now, trigger=trigger, started_by=user, slot=slot
    )
    try:
        result = job.func(run)
    except Exception as error:  # noqa: BLE001 - every failure is recorded, then the worker goes on
        # Only the kind of error is kept: a message can carry personal data.
        logger.warning("Job %s failed: %s", name, type(error).__name__)
        run.state = JobRun.State.FAILED
        run.message = _failure_message(error)
        run.finished_at = timezone.now()
        run.save(update_fields=["state", "message", "finished_at", "updated_at"])
        if job.notify_on_failure:
            _notify_owners(job, run)
    else:
        run.state = JobRun.State.DONE
        counts = result if isinstance(result, dict) else {}
        run.message = str(counts.pop("message", ""))[:500]
        run.counts = counts
        run.finished_at = timezone.now()
        run.save(update_fields=["state", "message", "counts", "finished_at", "updated_at"])
    finally:
        _release(name)
    return run


def _failure_message(error: Exception) -> str:
    text = getattr(error, "public_message", "") or type(error).__name__
    return f"Failed: {text}"[:500]


def _notify_owners(job: registry.Job, run: JobRun) -> None:
    from apps.accounts.models import User

    for owner in User.objects.active_owners():
        events.notify(
            owner,
            f"The background job “{job.label}” failed. It will be tried again at its next time.",
            reverse("jobs:list"),
        )


def due_jobs(now: datetime) -> list[tuple[registry.Job, datetime | None]]:
    """Jobs to run now, each with the slot it is for (None for a "Run now" request).

    A slot counts as done once any run has started for it, so a failed run is
    tried again at the next slot, not straight away.
    """
    due = []
    requested = set(
        JobLock.objects.filter(requested_at__isnull=False).values_list("name", flat=True)
    )
    for job in registry.all_jobs():
        if job.name in requested:
            due.append((job, None))
            continue
        slot = job.schedule.last_slot(now)
        last = JobRun.objects.filter(name=job.name, trigger=JobRun.Trigger.SCHEDULE).first()
        lock, _ = JobLock.objects.get_or_create(name=job.name)
        if last is None:
            # A new job starts at its first slot after it was first seen, not in the past.
            if lock.created_at > slot:
                continue
        elif last.slot and last.slot >= slot:
            continue
        due.append((job, slot))
    return due


def run_due(now: datetime | None = None) -> list[JobRun]:
    """Run everything due. Called by the worker once a minute."""
    now = now or timezone.now()
    heartbeat(now)
    runs = []
    for job, slot in due_jobs(now):
        lock = JobLock.objects.filter(name=job.name).first()
        user = lock.requested_by if (slot is None and lock) else None
        trigger = JobRun.Trigger.MANUAL if slot is None else JobRun.Trigger.SCHEDULE
        run = run_job(job.name, trigger=trigger, user=user, slot=slot, now=now)
        if run is not None:
            runs.append(run)
    return runs


def request_run(user, name: str) -> None:
    """ "Run now": the worker starts the job within a minute."""
    job = registry.get(name)
    with transaction.atomic():
        lock, _ = JobLock.objects.get_or_create(name=name)
        lock.requested_at = timezone.now()
        lock.requested_by = user
        lock.save(update_fields=["requested_at", "requested_by", "updated_at"])
    events.record(user, "job.requested", f"{user} asked for the job “{job.label}” to run now.")


def heartbeat(now: datetime) -> None:
    WorkerHeartbeat.objects.update_or_create(
        hostname=socket.gethostname()[:200], defaults={"seen_at": now}
    )


def worker_last_seen() -> datetime | None:
    beat = WorkerHeartbeat.objects.order_by("-seen_at").first()
    return beat.seen_at if beat else None


def last_runs() -> dict[str, JobRun]:
    runs = {}
    for job in registry.all_jobs():
        run = JobRun.objects.filter(name=job.name).first()
        if run:
            runs[job.name] = run
    return runs
