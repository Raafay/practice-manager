from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import PublicIdModel, TimeStampedModel


class PipelineStage(TimeStampedModel):
    """One column of the sales board. Edited in Settings."""

    name = models.CharField(max_length=60)
    key = models.SlugField(max_length=30, unique=True)
    position = models.PositiveSmallIntegerField(default=0)
    chance = models.PositiveSmallIntegerField(
        "chance of winning (%)", default=0, validators=[MaxValueValidator(100)]
    )
    is_open = models.BooleanField(default=True)
    is_won = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)
    is_on_hold = models.BooleanField(
        default=False, help_text="On hold prospects are never marked quiet."
    )
    colour = models.CharField(max_length=7, default="#64748b")

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name


class ProspectDetails(TimeStampedModel):
    """Sales details for a client that is or was a prospect. Source is on the client."""

    class LostReason(models.TextChoices):
        PRICE = "price", "Price"
        WENT_ELSEWHERE = "went_elsewhere", "Went elsewhere"
        NO_REPLY = "no_reply", "No reply"
        NOT_A_FIT = "not_a_fit", "Not a fit"
        TIMING = "timing", "Timing"
        OTHER = "other", "Other"

    client = models.OneToOneField(
        "clients.Client", on_delete=models.CASCADE, related_name="prospect"
    )
    stage = models.ForeignKey(PipelineStage, on_delete=models.PROTECT, related_name="prospects")
    stage_changed_at = models.DateTimeField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    enquiry_date = models.DateField(null=True, blank=True)
    expected_start = models.DateField(
        "expected start month", null=True, blank=True, help_text="The first day of the month."
    )
    expected_fee = models.DecimalField(
        "expected monthly fee",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Used only until services are ticked.",
    )
    setup_fee = models.DecimalField(
        "one-off setup fee",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    next_action = models.CharField(max_length=250, blank=True)
    next_action_date = models.DateField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    won_on = models.DateField(null=True, blank=True)
    lost_on = models.DateField(null=True, blank=True)
    lost_reason = models.CharField(max_length=20, choices=LostReason.choices, blank=True)
    lost_note = models.CharField(max_length=300, blank=True)
    quiet_notified_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "prospect details"

    def __str__(self) -> str:
        return f"Sales details for {self.client}"


class Meeting(TimeStampedModel):
    class Kind(models.TextChoices):
        FACE_TO_FACE = "face_to_face", "Face to face"
        PHONE = "phone", "Phone"
        VIDEO = "video", "Video"

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="meetings")
    held_at = models.DateTimeField()
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.FACE_TO_FACE)
    place = models.CharField(max_length=200, blank=True)
    staff = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    people = models.CharField("people from the client", max_length=300, blank=True)
    notes = models.TextField(blank=True)
    outcome = models.CharField(max_length=300, blank=True)
    follow_up = models.CharField(max_length=300, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-held_at", "-id"]

    def __str__(self) -> str:
        return f"Meeting with {self.client} on {self.held_at:%d/%m/%Y}"


class Proposal(PublicIdModel, TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Viewed"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        WITHDRAWN = "withdrawn", "Withdrawn"

    client = models.ForeignKey("clients.Client", on_delete=models.CASCADE, related_name="proposals")
    version = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    # A frozen copy of each service: name, description, fee, frequency.
    lines = models.JSONField(default=list, blank=True)
    monthly_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    setup_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    show_breakdown = models.BooleanField("show fee breakdown", default=True)
    show_inc_vat = models.BooleanField("show fees including VAT", default=False)
    show_vat_text = models.BooleanField("show VAT wording", default=True)
    # Frozen when the proposal is made: None means the practice is not VAT registered.
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    valid_until = models.DateField()
    opening_text = models.TextField(blank=True)
    what_next_html = models.TextField(blank=True)
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    message = models.ForeignKey(
        "comms.QueuedMessage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_to = models.CharField(max_length=300, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.CharField("decided by (typed name)", max_length=200, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True)
    decline_reason = models.CharField(max_length=500, blank=True)
    document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    accepted_document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["client", "version"], name="one_proposal_per_version")
        ]

    def __str__(self) -> str:
        return f"Proposal v{self.version} for {self.client}"

    @property
    def tone(self) -> str:
        return {
            "accepted": "green",
            "sent": "accent",
            "viewed": "accent",
            "draft": "neutral",
            "declined": "red",
            "expired": "amber",
            "withdrawn": "neutral",
        }[self.state]

    @property
    def is_editable(self) -> bool:
        return self.state == self.State.DRAFT

    @property
    def is_waiting(self) -> bool:
        return self.state in (self.State.SENT, self.State.VIEWED)


class PipelineSettings(TimeStampedModel):
    """One row: the quiet rule, proposal defaults and the starter wording."""

    quiet_days = models.PositiveSmallIntegerField(
        "Mark a prospect quiet after this many days with nothing happening",
        default=14,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    valid_days = models.PositiveSmallIntegerField(
        "A proposal stays open for (days)",
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    opening_text = models.TextField(blank=True)
    what_next_html = models.TextField("What happens next", blank=True)
    wording_is_starter = models.BooleanField(default=True)

    class Meta:
        verbose_name = "pipeline settings"
        verbose_name_plural = "pipeline settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "PipelineSettings":
        row, _ = cls.objects.get_or_create(pk=1)
        return row
