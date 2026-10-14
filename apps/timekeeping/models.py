from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class TimeEntry(TimeStampedModel):
    """Time one person spent. No client means internal time."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="time_entries"
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="time_entries"
    )
    service = models.ForeignKey(
        "services.Service", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    date = models.DateField(default=timezone.localdate, db_index=True)
    minutes = models.PositiveIntegerField()
    note = models.CharField(max_length=300, blank=True)
    billable = models.BooleanField(default=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "time entries"

    def __str__(self) -> str:
        return f"{self.user} {self.minutes} min on {self.date:%d/%m/%Y}"

    @property
    def hours_text(self) -> str:
        from .services import format_minutes

        return format_minutes(self.minutes)


class Timer(TimeStampedModel):
    """A running timer. The one-to-one link means a person cannot have two."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="running_timer"
    )
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        return f"Timer for {self.user}"

    @property
    def label(self) -> str:
        if self.task_id:
            return self.task.title
        if self.client_id:
            return self.client.name
        return "Internal time"
