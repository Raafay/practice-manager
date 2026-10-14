import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel

LEVELS = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


class AmlSettings(TimeStampedModel):
    """Practice-wide AML settings and records. One row."""

    supervisory_body = models.CharField(max_length=200, blank=True)
    nominated_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    medium_from = models.PositiveSmallIntegerField(
        "Medium risk from a score of", default=5, validators=[MinValueValidator(1)]
    )
    high_from = models.PositiveSmallIntegerField(
        "High risk from a score of", default=10, validators=[MinValueValidator(2)]
    )
    review_months_high = models.PositiveSmallIntegerField(
        "Review high-risk clients every (months)",
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    review_months_medium = models.PositiveSmallIntegerField(
        "Review medium-risk clients every (months)",
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    review_months_low = models.PositiveSmallIntegerField(
        "Review low-risk clients every (months)",
        default=36,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
    )
    higher_risk_services = models.ManyToManyField(
        "services.Service",
        blank=True,
        related_name="+",
        verbose_name="Services that prompt an AML review when added",
    )
    training_reminder_months = models.PositiveSmallIntegerField(default=12)

    class Meta:
        verbose_name = "AML settings"
        verbose_name_plural = "AML settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "AmlSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def review_months(self, level: str) -> int:
        return {
            "high": self.review_months_high,
            "medium": self.review_months_medium,
            "low": self.review_months_low,
        }[level]

    def level_for(self, score: int, enhanced: bool = False) -> str:
        if enhanced or score >= self.high_from:
            return "high"
        return "medium" if score >= self.medium_from else "low"


class TrainingRecord(TimeStampedModel):
    person = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="aml_training"
    )
    trained_on = models.DateField()
    course = models.CharField(max_length=200)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-trained_on", "-id"]

    def __str__(self) -> str:
        return f"{self.person}: {self.course}"


def policy_upload_to(instance, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"policy/{uuid.uuid4().hex}/{uuid.uuid4().hex}.{extension}"


class PolicyDocument(TimeStampedModel):
    """The practice's own AML policy documents. Staff only, never a public address."""

    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=policy_upload_to, max_length=200)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class IdentityCheck(TimeStampedModel):
    class State(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        REQUESTED = "requested", "Requested"
        RECEIVED = "received", "Received"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    class Method(models.TextChoices):
        IN_PERSON = "in_person", "Original seen in person"
        POST_OFFICE = "post_office", "Post Office certified copy"
        CERTIFIED = "certified", "Copy certified by a professional"
        ELECTRONIC = "electronic", "Electronic check"
        OTHER = "other", "Other"

    class DocType(models.TextChoices):
        PASSPORT = "passport", "Passport"
        DRIVING = "driving_licence", "Driving licence"
        NATIONAL_ID = "national_id", "National identity card"
        OTHER = "other", "Other"

    class AddressProof(models.TextChoices):
        UTILITY = "utility", "Utility bill"
        BANK = "bank", "Bank statement"
        COUNCIL_TAX = "council_tax", "Council tax bill"
        TENANCY = "tenancy", "Tenancy agreement"
        OTHER = "other", "Other"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="identity_checks"
    )
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.CASCADE, related_name="identity_checks"
    )
    state = models.CharField(max_length=12, choices=State.choices, default=State.NOT_STARTED)
    method = models.CharField(max_length=12, choices=Method.choices, blank=True)
    document_type = models.CharField(max_length=16, choices=DocType.choices, blank=True)
    document_expiry = models.DateField(null=True, blank=True)
    proof_of_address = models.CharField(
        "proof of address type", max_length=12, choices=AddressProof.choices, blank=True
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    documents = models.ManyToManyField("clients.Document", blank=True, related_name="+")
    # Taken off the list by staff, with a reason.
    excluded = models.BooleanField(default=False)
    excluded_reason = models.CharField(max_length=300, blank=True)
    added_by_hand = models.BooleanField(default=False)
    added_reason = models.CharField(max_length=300, blank=True)
    expiry_notified_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["contact__last_name", "contact__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["client", "contact"], name="one_identity_check")
        ]

    def __str__(self) -> str:
        return f"Identity of {self.contact} for {self.client}"

    @property
    def tone(self) -> str:
        return {
            "verified": "green",
            "failed": "red",
            "expired": "red",
            "received": "accent",
            "requested": "accent",
        }.get(self.state, "neutral")


class RiskQuestion(TimeStampedModel):
    class AnswerType(models.TextChoices):
        YES_NO = "yes_no", "Yes or no"
        CHOICE = "choice", "A choice"

    section = models.CharField(max_length=80)
    text = models.CharField(max_length=300)
    help_text = models.TextField(blank=True)
    answer_type = models.CharField(
        max_length=8, choices=AnswerType.choices, default=AnswerType.YES_NO
    )
    # [{"value": "yes", "label": "Yes", "score": 3, "enhanced": false}, ...]
    options = models.JSONField(default=list)
    records_check = models.BooleanField("record the date checked and how", default=False)
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.text

    def option(self, value: str) -> dict | None:
        return next((o for o in self.options if o["value"] == value), None)


class RiskAssessment(TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Awaiting approval"
        APPROVED = "approved", "Approved"
        SENT_BACK = "sent_back", "Sent back"
        SUPERSEDED = "superseded", "Replaced by a newer review"

    OPEN_STATES = ("draft", "submitted", "sent_back")

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="risk_assessments"
    )
    version = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT)
    # {question id: {"text", "section", "answer", "label", "score", "enhanced", "note",
    #                "checked_on", "checked_how"}}
    answers = models.JSONField(default=dict, blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    suggested_level = models.CharField(max_length=6, choices=LEVELS, blank=True)
    level = models.CharField(max_length=6, choices=LEVELS, blank=True)
    level_reason = models.CharField(max_length=300, blank=True)
    enhanced_needed = models.BooleanField(default=False)
    enhanced_notes = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    review_reason = models.CharField(max_length=300, blank=True)
    send_back_reason = models.CharField(max_length=300, blank=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    assessed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    next_review_due = models.DateField(null=True, blank=True)
    review_task_made = models.BooleanField(default=False)
    ch_snapshot_document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "version"], name="one_assessment_per_version"
            ),
            models.UniqueConstraint(
                fields=["client"],
                condition=models.Q(state__in=["draft", "submitted", "sent_back"]),
                name="one_open_assessment_per_client",
            ),
        ]

    def __str__(self) -> str:
        return f"Risk assessment v{self.version} for {self.client}"

    @property
    def is_open(self) -> bool:
        return self.state in self.OPEN_STATES

    @property
    def is_editable(self) -> bool:
        return self.state in (self.State.DRAFT, self.State.SENT_BACK)

    @property
    def level_tone(self) -> str:
        return {"low": "green", "medium": "amber", "high": "red"}.get(self.level, "neutral")


class ReviewPrompt(TimeStampedModel):
    """A reason to review a client's assessment sooner than its date."""

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="aml_review_prompts"
    )
    reason = models.CharField(max_length=300)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.client}: {self.reason}"
