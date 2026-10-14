from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel

DUE_SOON_DAYS = 14


class Service(TimeStampedModel):
    class Kind(models.TextChoices):
        COMPLIANCE = "compliance", "Compliance"
        ADVISORY = "advisory", "Advisory"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.COMPLIANCE)
    # Client type values this service applies to, for example ["ltd", "llp"].
    applies_to = models.JSONField(default=list)
    default_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    description = models.TextField("description for proposals", blank=True)
    schedule_text = models.TextField("engagement letter schedule text", blank=True)
    # Names of deadline rules this service creates (apps/services/rules).
    rules = models.JSONField(default=list, blank=True)
    renewal = models.BooleanField(
        "yearly renewal", default=False, help_text="Asks for a renewal date, due on that date."
    )
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self) -> str:
        return self.name

    def applies_to_type(self, client_type: str) -> bool:
        return client_type in (self.applies_to or [])


class ClientService(TimeStampedModel):
    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"
        ONE_OFF = "one_off", "One-off"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="client_services"
    )
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="client_services")
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fee_frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY
    )
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    # Anything service-specific: frequency, due_days, renewal, paye_quarterly, ...
    settings = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["service__position", "service__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "service"],
                condition=~Q(state="ended"),
                name="one_open_row_per_client_service",
            )
        ]

    def __str__(self) -> str:
        return f"{self.service} for {self.client}"

    @property
    def is_open(self) -> bool:
        return self.state != self.State.ENDED

    @property
    def monthly_equivalent(self) -> Decimal | None:
        """Pounds a month, rounded half up to pence. One-off fees count as nothing recurring."""
        from .fees import monthly_equivalent

        return monthly_equivalent(self.fee_amount, self.fee_frequency)


class FeeChange(TimeStampedModel):
    client_service = models.ForeignKey(
        ClientService, on_delete=models.CASCADE, related_name="fee_changes"
    )
    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_frequency = models.CharField(max_length=10, blank=True)
    new_frequency = models.CharField(max_length=10, blank=True)
    effective_on = models.DateField(default=timezone.localdate)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-effective_on", "-id"]


class DeadlineQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status=Deadline.Status.OPEN)

    def overdue(self, today: date | None = None):
        return self.open().filter(due_date__lt=today or timezone.localdate())

    def due_within(self, days: int, today: date | None = None):
        today = today or timezone.localdate()
        return self.open().filter(due_date__lte=today + timedelta(days=days))

    def for_portal_user(self, user):
        """Open deadlines of the person's clients. The portal shows the label and date only."""
        from apps.clients.models import Client

        return self.open().filter(client__in=Client.objects.for_portal_user(user))


class Deadline(TimeStampedModel):
    class Source(models.TextChoices):
        COMPANIES_HOUSE = "companies_house", "Companies House"
        CALCULATED = "calculated", "Calculated"
        MANUAL = "manual", "Changed by hand"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DONE = "done", "Done"
        NOT_REQUIRED = "not_required", "Not required"

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="deadlines")
    client_service = models.ForeignKey(
        ClientService, on_delete=models.SET_NULL, null=True, blank=True, related_name="deadlines"
    )
    rule = models.CharField(max_length=40)
    period_key = models.CharField(max_length=20)
    label = models.CharField(max_length=200)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    due_date = models.DateField(db_index=True)
    original_due_date = models.DateField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.CALCULATED)
    source_note = models.CharField(max_length=300, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    done_on = models.DateField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    done_note = models.CharField(max_length=500, blank=True)
    evidence = models.CharField(max_length=500, blank=True)
    override_reason = models.CharField(max_length=300, blank=True)

    objects = DeadlineQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "rule", "period_key"], name="one_deadline_per_period"
            )
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.client})"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN

    @property
    def rule_title(self) -> str:
        from .rules import REGISTRY

        info = REGISTRY.get(self.rule)
        return info.title if info else self.rule

    def shown_state(self, today: date | None = None) -> str:
        """Worked out, never stored: done, not_required, overdue, due_soon or upcoming."""
        today = today or timezone.localdate()
        if self.status != self.Status.OPEN:
            return self.status
        if self.due_date < today:
            return "overdue"
        if self.due_date <= today + timedelta(days=DUE_SOON_DAYS):
            return "due_soon"
        return "upcoming"

    @property
    def state_label_tone(self) -> tuple[str, str]:
        return {
            "done": ("Done", "green"),
            "not_required": ("Not required", "neutral"),
            "overdue": ("Overdue", "red"),
            "due_soon": ("Due soon", "amber"),
            "upcoming": ("Upcoming", "accent"),
        }[self.shown_state()]

    @property
    def changed_by_hand(self) -> bool:
        return self.source == self.Source.MANUAL
