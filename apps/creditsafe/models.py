from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class CreditCheck(TimeStampedModel):
    """One Creditsafe report for a client's company. Each is kept, so the history shows."""

    class Source(models.TextChoices):
        CHECK = "check", "Checked by hand"
        ALERT = "alert", "Monitoring alert"
        DEMO = "demo", "Demo data"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="credit_checks"
    )
    company_number = models.CharField(max_length=12)
    connect_id = models.CharField(max_length=60, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    rating = models.CharField(max_length=4, blank=True)  # Creditsafe's common band, A to E
    rating_description = models.CharField(max_length=100, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.CHECK)
    reason = models.CharField(max_length=300, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.client}: {self.rating or '?'} ({self.score})"

    @property
    def tone(self) -> str:
        return {"A": "green", "B": "green", "C": "amber", "D": "red", "E": "red"}.get(
            self.rating, "neutral"
        )


class MonitoringState(TimeStampedModel):
    """One row: where the monitoring alert feed was last read up to."""

    last_event_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]
