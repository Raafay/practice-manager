import re
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_hex_colour(value: str) -> None:
    if not HEX_COLOUR.match(value or ""):
        raise ValidationError(
            "Enter a colour as # followed by six hex digits, for example #2f5d8a."
        )


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    """Anything shown in the portal or a public link is looked up by this, never by its number."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


def logo_upload_to(instance, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"practice/{uuid.uuid4().hex}/{uuid.uuid4().hex}.{extension}"


class PracticeSettings(TimeStampedModel):
    """One row holding the practice's own details. Later stages add fields."""

    CACHE_KEY = "practice-settings"

    practice_name = models.CharField(max_length=200, default="Our practice")
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    logo = models.FileField(upload_to=logo_upload_to, blank=True)
    logo_content_type = models.CharField(max_length=50, blank=True, editable=False)
    accent_colour = models.CharField(
        max_length=7, default="#2f5d8a", validators=[validate_hex_colour]
    )
    vat_registered = models.BooleanField("VAT registered", default=False)
    vat_rate = models.DecimalField(
        "VAT rate (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    # Sign-in and sessions for staff. Changed by the owner only.
    mfa_trust_enabled = models.BooleanField("Allow “trust this browser” for 30 days", default=True)
    session_idle_minutes = models.PositiveIntegerField(
        "Sign out after this many idle minutes",
        default=60,
        validators=[MinValueValidator(5), MaxValueValidator(24 * 60)],
    )
    session_max_hours = models.PositiveIntegerField(
        "Sign out after this many hours in any case",
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )

    # Retention. Nothing is deleted automatically: these set the dates on a client.
    retention_years = models.PositiveSmallIntegerField(
        "Keep client records for (years after the relationship ends)",
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
    )
    aml_retention_years = models.PositiveSmallIntegerField(
        "Keep AML records for (years after the relationship ends)",
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
    )

    # Email to clients (Stage 6).
    sending_address = models.EmailField(
        "Sending address",
        blank=True,
        help_text="Messages to clients come from this address, with the staff member's name. "
        "Leave blank to use the practice email.",
    )
    bcc_practice = models.BooleanField(
        "Copy every sent email to the practice address", default=False
    )
    comms_paused = models.BooleanField("Pause all automatic sending", default=False)
    comms_paused_at = models.DateTimeField(null=True, blank=True)
    comms_paused_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "practice settings"
        verbose_name_plural = "practice settings"

    def __str__(self) -> str:
        return self.practice_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):
        raise ValidationError("Practice settings cannot be deleted.")

    @classmethod
    def load(cls) -> "PracticeSettings":
        settings_row = cache.get(cls.CACHE_KEY)
        if settings_row is None:
            settings_row, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, settings_row, 300)
        return settings_row


class StoredBankHolidays(TimeStampedModel):
    """England and Wales bank holidays fetched from gov.uk by the monthly job.

    One row. Its years replace the bundled list's same years; other years keep
    the bundled dates. If it is empty or missing, the bundled list is used.
    """

    dates = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "stored bank holidays"
        verbose_name_plural = "stored bank holidays"

    def __str__(self) -> str:
        return f"{len(self.dates)} bank holidays"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
