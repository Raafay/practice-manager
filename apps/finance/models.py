from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel


class FinanceSettings(TimeStampedModel):
    """One row. Owner-only settings for the Finance pages and the weekly summary."""

    target_hourly_rate = models.DecimalField(
        "Target hourly rate (£)", max_digits=10, decimal_places=2, default=Decimal("60.00")
    )
    not_invoiced_after_day = models.PositiveSmallIntegerField(
        "Clients with no invoice this month are listed after day",
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
    )
    default_start_days = models.PositiveSmallIntegerField(
        "A prospect with no expected start is assumed to start this many days from today",
        default=60,
        validators=[MinValueValidator(0), MaxValueValidator(365)],
    )
    summary_weekday = models.PositiveSmallIntegerField(
        "Owner summary day",
        default=4,
        choices=[
            (i, n)
            for i, n in enumerate(
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            )
        ],
    )
    summary_hour = models.PositiveSmallIntegerField(
        "Owner summary hour (0 to 23)",
        default=15,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
    )
    summary_last_sent_on = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name_plural = "finance settings"

    @classmethod
    def load(cls) -> "FinanceSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Target(TimeStampedModel):
    """The monthly recurring income the owner wants in one month (first day of the month)."""

    month = models.DateField(unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["month"]

    def __str__(self) -> str:
        return f"{self.month:%m/%Y}: {self.amount}"


class XeroConnection(TimeStampedModel):
    """The practice's one Xero organisation. Tokens are encrypted."""

    tenant_id = models.CharField(max_length=64)
    tenant_name = models.CharField(max_length=200, blank=True)
    access_token = EncryptedTextField(blank=True, default="")
    refresh_token = EncryptedTextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_good_sync_at = models.DateTimeField(null=True, blank=True)
    # Invoices and credit notes changed since this moment are read next time.
    modified_since = models.DateTimeField(null=True, blank=True)
    broken = models.BooleanField(default=False)
    last_error = models.CharField(max_length=300, blank=True)

    def __str__(self) -> str:
        return self.tenant_name or self.tenant_id


class XeroContact(TimeStampedModel):
    class Match(models.TextChoices):
        NONE = "none", "Not matched"
        SUGGESTED = "suggested", "Suggested"
        CONFIRMED = "confirmed", "Confirmed"
        IGNORED = "ignored", "Ignored"

    xero_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=300)
    email = models.CharField(max_length=300, blank=True)
    archived = models.BooleanField(default=False)
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="xero_contacts",
    )
    suggested_client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    match_state = models.CharField(max_length=10, choices=Match.choices, default=Match.NONE)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class XeroInvoice(TimeStampedModel):
    """A sales invoice (type ACCREC) as Xero holds it. Read only."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        AUTHORISED = "AUTHORISED", "Awaiting payment"
        PAID = "PAID", "Paid"
        VOIDED = "VOIDED", "Voided"
        DELETED = "DELETED", "Deleted"

    xero_id = models.CharField(max_length=64, unique=True)
    number = models.CharField(max_length=60, blank=True)
    reference = models.CharField(max_length=300, blank=True)
    contact = models.ForeignKey(
        XeroContact, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices"
    )
    contact_name = models.CharField(max_length=300, blank=True)
    date = models.DateField(null=True, db_index=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, db_index=True)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    amount_credited = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="GBP")
    updated_utc = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return self.number or self.xero_id

    @property
    def client(self):
        return self.contact.client if self.contact_id else None

    @property
    def counts(self) -> bool:
        return self.status in (self.Status.AUTHORISED, self.Status.PAID)

    def days_overdue(self, today: date) -> int:
        if self.due_date is None or self.due_date >= today:
            return 0
        return (today - self.due_date).days


class XeroCreditNote(TimeStampedModel):
    xero_id = models.CharField(max_length=64, unique=True)
    number = models.CharField(max_length=60, blank=True)
    contact = models.ForeignKey(
        XeroContact, on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_notes"
    )
    contact_name = models.CharField(max_length=300, blank=True)
    date = models.DateField(null=True, db_index=True)
    status = models.CharField(max_length=12)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    remaining_credit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    updated_utc = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return self.number or self.xero_id

    @property
    def counts(self) -> bool:
        return self.status in ("AUTHORISED", "PAID")


class XeroSyncLog(TimeStampedModel):
    class State(models.TextChoices):
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=8, choices=State.choices, default=State.DONE)
    message = models.CharField(max_length=300, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    calls = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-id"]
