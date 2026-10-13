from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class JobLock(TimeStampedModel):
    """One row per job. `running_since` set means a worker holds the job.

    `requested_at` is set by "Run now" and cleared when the worker starts the run.
    """

    name = models.CharField(max_length=60, unique=True)
    running_since = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def __str__(self) -> str:
        return self.name


class JobRun(TimeStampedModel):
    class State(models.TextChoices):
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        MANUAL = "manual", "Run now"
        COMMAND = "command", "Command"

    name = models.CharField(max_length=60, db_index=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.RUNNING)
    trigger = models.CharField(max_length=10, choices=Trigger.choices, default=Trigger.SCHEDULE)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The time slot this run was for, so a slot is never run twice by the schedule.
    slot = models.DateTimeField(null=True, blank=True)
    message = models.CharField(max_length=500, blank=True)
    counts = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [models.Index(fields=["name", "-started_at"])]

    def __str__(self) -> str:
        return f"{self.name} {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def state_tone(self) -> str:
        return {"done": "green", "failed": "red", "running": "accent"}.get(self.state, "neutral")

    @property
    def duration_seconds(self) -> int | None:
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.started_at).total_seconds())


class WorkerHeartbeat(TimeStampedModel):
    """When a worker last looked for due jobs, so the Jobs page can say if one is running."""

    hostname = models.CharField(max_length=200, unique=True)
    seen_at = models.DateTimeField()

    def __str__(self) -> str:
        return self.hostname
