from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.fields import EncryptedTextField
from apps.core.models import PublicIdModel, TimeStampedModel


class ChecklistTemplateItem(TimeStampedModel):
    """One line of the onboarding checklist template, edited in Settings."""

    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=200)
    needed_before_golive = models.BooleanField("needed before go-live", default=False)
    system_ticked = models.BooleanField(
        "ticked by the system", default=False, help_text="Shown for information only."
    )
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name


class OnboardingItem(TimeStampedModel):
    class State(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"
        NOT_NEEDED = "not_needed", "Not needed"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="onboarding_items"
    )
    key = models.SlugField(max_length=40)
    name = models.CharField(max_length=200)
    needed_before_golive = models.BooleanField(default=False)
    state = models.CharField(max_length=12, choices=State.choices, default=State.TODO)
    done_on = models.DateField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.CharField(max_length=300, blank=True)
    set_by_system = models.BooleanField(default=False)
    # True while the done state came from the system, so it can be put back if it stops holding.
    auto_ticked = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["client", "key"], name="one_item_per_key_per_client")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.client})"

    @property
    def is_finished(self) -> bool:
        return self.state in (self.State.DONE, self.State.NOT_NEEDED)

    @property
    def tone(self) -> str:
        return {"done": "green", "in_progress": "accent", "not_needed": "neutral"}.get(
            self.state, "amber" if self.needed_before_golive else "neutral"
        )


class LetterPart(TimeStampedModel):
    """Standard wording for engagement letters: covering letter, terms, privacy notice."""

    class Key(models.TextChoices):
        COVERING = "covering", "Covering letter"
        TERMS = "terms", "Standard terms"
        PRIVACY = "privacy", "Privacy notice"

    key = models.CharField(max_length=10, choices=Key.choices, unique=True)
    body = models.TextField(blank=True)
    # True until someone edits the wording. Drives the "starter text" banner.
    starter = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:
        return self.get_key_display()


class EngagementLetter(PublicIdModel, TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        VIEWED = "viewed", "Viewed"
        SIGNED = "signed", "Signed"
        REPLACED = "replaced", "Replaced"
        CANCELLED = "cancelled", "Cancelled"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="engagement_letters"
    )
    version = models.PositiveSmallIntegerField(default=1)
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    # The services and fees as they stood when the letter was prepared.
    services = models.JSONField(default=list, blank=True)
    body_html = models.TextField(blank=True)
    signer = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    unsigned_document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    signed_document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    fingerprint = models.CharField(max_length=64, blank=True)
    message = models.ForeignKey(
        "comms.QueuedMessage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    typed_name = models.CharField(max_length=200, blank=True)
    signer_email = models.EmailField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    review_due = models.DateField(null=True, blank=True)
    review_task_made = models.BooleanField(default=False)

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["client", "version"], name="one_letter_per_version")
        ]

    def __str__(self) -> str:
        return f"Engagement letter v{self.version} for {self.client}"

    @property
    def tone(self) -> str:
        return {
            "signed": "green",
            "sent": "accent",
            "viewed": "accent",
            "draft": "neutral",
            "replaced": "neutral",
            "cancelled": "red",
        }[self.state]

    @property
    def is_editable(self) -> bool:
        return self.state == self.State.DRAFT


class ClearanceRequest(TimeStampedModel):
    """Professional clearance: asking the previous accountant to hand over."""

    ITEMS = [
        ("last_accounts", "Last accounts"),
        ("tax_returns", "Tax returns"),
        ("trial_balance", "Trial balance"),
        ("payroll_records", "Payroll records"),
        ("vat_workings", "VAT workings"),
    ]

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="clearance_requests"
    )
    accountant_name = models.CharField("previous accountant", max_length=150)
    firm = models.CharField(max_length=200, blank=True)
    email = models.EmailField()
    asked_for = models.JSONField(default=list, blank=True)
    received = models.JSONField(default=list, blank=True)
    sent_on = models.DateField(null=True, blank=True)
    chased_on = models.DateField(null=True, blank=True)
    reply_received_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    letter_document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Clearance for {self.client} from {self.accountant_name}"

    @property
    def asked_labels(self) -> list[str]:
        names = dict(self.ITEMS)
        return [names[k] for k in self.asked_for if k in names]


class AgentAuthorisation(TimeStampedModel):
    class Tax(models.TextChoices):
        SA = "sa", "Self Assessment"
        CT = "ct", "Corporation Tax"
        PAYE = "paye", "PAYE"
        VAT = "vat", "VAT"
        CIS = "cis", "CIS"
        MTD_VAT = "mtd_vat", "Making Tax Digital for VAT"
        MTD_IT = "mtd_it", "Making Tax Digital for Income Tax"
        OTHER = "other", "Other"

    class Method(models.TextChoices):
        POST_CODE = "post_code", "Code by post"
        HANDSHAKE = "handshake", "Digital handshake link"
        FORM_64_8 = "form_64_8", "Paper form 64-8"
        HELD = "held", "Already held"

    class State(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        REQUESTED = "requested", "Requested"
        CODE_RECEIVED = "code_received", "Code received"
        SUBMITTED = "submitted", "Submitted"
        AUTHORISED = "authorised", "Authorised"
        EXPIRED = "expired", "Expired"
        REJECTED = "rejected", "Rejected"

    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="agent_authorisations"
    )
    tax = models.CharField(max_length=10, choices=Tax.choices)
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.POST_CODE)
    state = models.CharField(max_length=14, choices=State.choices, default=State.NOT_STARTED)
    requested_on = models.DateField(null=True, blank=True)
    code = EncryptedTextField("HMRC code", blank=True)
    code_received_on = models.DateField(null=True, blank=True)
    code_expires_on = models.DateField(null=True, blank=True)
    link_sent_on = models.DateField(null=True, blank=True)
    link_expires_on = models.DateField(null=True, blank=True)
    authorised_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    expiry_notified_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["tax", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "tax"],
                condition=Q(tax__in=["sa", "ct", "paye", "vat", "cis", "mtd_vat", "mtd_it"])
                & ~Q(state="expired"),
                name="one_live_authorisation_per_tax",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_tax_display()} for {self.client}"

    @property
    def expiry(self):
        """The date that matters while the request is waiting: link or code expiry."""
        if self.state in ("authorised", "expired", "rejected", "not_started"):
            return None
        return self.link_expires_on or self.code_expires_on

    @property
    def tone(self) -> str:
        return {
            "authorised": "green",
            "expired": "red",
            "rejected": "red",
            "not_started": "neutral",
        }.get(self.state, "accent")
