"""Portal sign-in codes, things to do, portal forms and requests (spec 08)."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.clients.models import Client
from apps.core.models import PublicIdModel, TimeStampedModel


def portal_clients(user):
    """The clients a portal user may see (see ClientQuerySet.for_portal_user)."""
    return Client.objects.for_portal_user(user)


class PortalLoginCode(TimeStampedModel):
    """A six-digit sign-in code. Only its hash is stored. Ten minutes, five tries."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="portal_codes"
    )
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PortalItemQuerySet(models.QuerySet):
    def for_portal_user(self, user):
        return self.filter(client__in=portal_clients(user)).filter(
            Q(contact__isnull=True) | Q(contact__portal_user=user)
        )

    def open(self):
        return self.filter(state=PortalItem.State.OPEN)


class PortalItem(PublicIdModel, TimeStampedModel):
    class Kind(models.TextChoices):
        SIGN_LETTER = "sign_letter", "Sign an engagement letter"
        ACCEPT_PROPOSAL = "accept_proposal", "Read a proposal"
        UPLOAD_RECORDS = "upload_records", "Upload records"
        CONFIRM_DETAILS = "confirm_details", "Confirm company details"
        CLIENT_DETAILS = "client_details", "Fill in your details"
        APPROVE_DOCUMENT = "approve_document", "Approve a document"

    class State(models.TextChoices):
        OPEN = "open", "Open"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="portal_items")
    contact = models.ForeignKey(
        "clients.Contact",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="portal_items",
        help_text="Empty means any portal user of the client.",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # The letter, proposal or document this item is about (by number, checked against the client).
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="portal_items"
    )
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = PortalItemQuerySet.as_manager()

    class Meta:
        ordering = ["state", "due_date", "-created_at"]
        indexes = [models.Index(fields=["client", "state"])]

    def __str__(self) -> str:
        return self.title

    @property
    def is_open(self) -> bool:
        return self.state == self.State.OPEN

    @property
    def button_label(self) -> str:
        return {
            self.Kind.SIGN_LETTER: "Read and sign",
            self.Kind.ACCEPT_PROPOSAL: "View proposal",
            self.Kind.UPLOAD_RECORDS: "Upload",
            self.Kind.CONFIRM_DETAILS: "Check details",
            self.Kind.CLIENT_DETAILS: "Fill in",
            self.Kind.APPROVE_DOCUMENT: "Read and approve",
        }[self.kind]


class PortalFormQuerySet(models.QuerySet):
    def for_portal_user(self, user):
        return self.filter(item__in=PortalItem.objects.for_portal_user(user))


class PortalForm(PublicIdModel, TimeStampedModel):
    """The answers to a confirmation statement check or the client details form."""

    class Kind(models.TextChoices):
        CONFIRMATION = "confirmation", "Confirmation statement check"
        DETAILS = "details", "Client details"

    class State(models.TextChoices):
        DRAFT = "draft", "In progress"
        SUBMITTED = "submitted", "Submitted"
        REVIEWED = "reviewed", "Reviewed"

    item = models.OneToOneField(PortalItem, on_delete=models.CASCADE, related_name="form")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="portal_forms")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    answers = models.JSONField(default=dict, blank=True)
    # Fields staff have applied or dismissed on the review screen: {"field": "applied"|"dismissed"}.
    review = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = PortalFormQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} for {self.client}"


class RequestQuerySet(models.QuerySet):
    def for_portal_user(self, user):
        return self.filter(client__in=portal_clients(user), channel=Request.Channel.PORTAL)

    def new(self):
        return self.filter(state=Request.State.NEW)

    def open(self):
        return self.filter(state__in=(Request.State.NEW, Request.State.IN_PROGRESS))


class Request(PublicIdModel, TimeStampedModel):
    class Channel(models.TextChoices):
        FORM = "form", "Request link"
        PORTAL = "portal", "Portal"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        PHONE = "phone", "Phone"
        IN_PERSON = "in_person", "In person"

    class State(models.TextChoices):
        NEW = "new", "New"
        IN_PROGRESS = "in_progress", "In progress"
        ANSWERED = "answered", "Answered"
        CLOSED = "closed", "Closed"
        SPAM = "spam", "Spam"

    class Urgency(models.TextChoices):
        NORMAL = "normal", "Normal"
        URGENT = "urgent", "Urgent"

    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sender_name = models.CharField(max_length=150, blank=True)
    sender_email = models.EmailField(blank=True)
    sender_phone = models.CharField(max_length=40, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.FORM)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    urgency = models.CharField(max_length=8, choices=Urgency.choices, default=Urgency.NORMAL)
    state = models.CharField(max_length=12, choices=State.choices, default=State.NEW, db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    closing_note = models.CharField(max_length=500, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # A question from the proposal page keeps the proposal it was about.
    proposal_id = models.PositiveBigIntegerField(null=True, blank=True)

    objects = RequestQuerySet.as_manager()

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self) -> str:
        return self.subject or f"Request {self.reference}"

    @property
    def reference(self) -> str:
        return f"R{self.pk:05d}" if self.pk else ""

    @property
    def is_open(self) -> bool:
        return self.state in (self.State.NEW, self.State.IN_PROGRESS)

    @property
    def state_tone(self) -> str:
        return {
            "new": "accent",
            "in_progress": "amber",
            "answered": "green",
            "closed": "neutral",
            "spam": "red",
        }[self.state]


def attachment_upload_to(instance, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"requests/{uuid.uuid4().hex}/{uuid.uuid4().hex}.{extension}"


class RequestFile(PublicIdModel, TimeStampedModel):
    """A file sent with a request. It becomes a Document when the request is converted."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to=attachment_upload_to, max_length=200)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    document = models.ForeignKey(
        "clients.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.original_name
