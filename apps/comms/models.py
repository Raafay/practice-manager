from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "Text message"
    LETTER = "letter", "Letter"


class MessageTemplate(TimeStampedModel):
    class Group(models.TextChoices):
        RECORDS = "records", "Records request"
        REMINDER = "reminder", "Reminder"
        DEADLINE = "deadline", "Deadline"
        PROPOSAL = "proposal", "Proposal"
        ONBOARDING = "onboarding", "Onboarding"
        FEES = "fees", "Fees"
        GENERAL = "general", "General"

    class SendMode(models.TextChoices):
        HOLD = "hold", "Hold for approval"
        AUTO = "auto", "Send automatically"

    key = models.CharField(
        max_length=60, blank=True, help_text="A fixed name for system templates."
    )
    name = models.CharField(max_length=150)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    group = models.CharField(max_length=12, choices=Group.choices, default=Group.GENERAL)
    subject = models.CharField(max_length=250, blank=True)
    body = models.TextField(blank=True)  # cleaned HTML for email and letters, plain text for texts
    send_mode = models.CharField(max_length=5, choices=SendMode.choices, default=SendMode.HOLD)
    active = models.BooleanField(default=True)
    system = models.BooleanField(default=False, help_text="System templates cannot be deleted.")

    class Meta:
        ordering = ["group", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["key"], condition=~Q(key=""), name="message_template_key_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class QueuedMessage(TimeStampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        NEEDS_APPROVAL = "needs_approval", "Needs approval"
        APPROVED = "approved", "Approved"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Delivery(models.TextChoices):
        DELIVERED = "delivered", "Delivered"
        BOUNCED = "bounced", "Bounced"
        COMPLAINED = "complained", "Complained"

    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    template = models.ForeignKey(
        MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, related_name="queued_messages"
    )
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to = models.CharField(max_length=500, blank=True, help_text="Comma separated addresses.")
    cc = models.CharField(max_length=500, blank=True)
    bcc = models.CharField(max_length=500, blank=True)
    subject = models.CharField(max_length=250, blank=True)
    body_html = models.TextField(blank=True)
    body_text = models.TextField(blank=True)
    attachments = models.ManyToManyField("clients.Document", blank=True, related_name="+")
    state = models.CharField(
        max_length=15, choices=State.choices, default=State.NEEDS_APPROVAL, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    deadline = models.ForeignKey(
        "services.Deadline", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    send_after = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=500, blank=True)
    delivery_state = models.CharField(max_length=12, choices=Delivery.choices, blank=True)
    duplicate_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    # "mine" signature, "none" or a blank for the template's own text.
    uses_signature = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state", "send_after"])]

    def __str__(self) -> str:
        return f"{self.subject or '(no subject)'} to {self.client}"

    @property
    def to_list(self) -> list[str]:
        return split_addresses(self.to)

    @property
    def is_editable(self) -> bool:
        return self.state in (self.State.DRAFT, self.State.NEEDS_APPROVAL, self.State.FAILED)


def split_addresses(value: str) -> list[str]:
    return [part.strip() for part in (value or "").replace(";", ",").split(",") if part.strip()]


class ReminderSchedule(TimeStampedModel):
    class Trigger(models.TextChoices):
        BEFORE_DEADLINE = "before_deadline", "Days before the due date"
        BEFORE_TARGET = "before_target", "Days before the task's target date"
        AFTER_PERIOD_END = "after_period_end", "Days after the period ends"
        STEP_TICKED = "step_ticked", "When a named step is ticked"

    key = models.CharField(max_length=60, blank=True)
    name = models.CharField(max_length=150)
    template = models.ForeignKey(
        MessageTemplate, on_delete=models.PROTECT, related_name="schedules"
    )
    rule = models.CharField(
        max_length=40, blank=True, help_text="The deadline rule this belongs to."
    )
    task_template = models.ForeignKey(
        "tasks.TaskTemplate", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    offsets = models.JSONField(default=list, help_text="Days, for example [30, 7].")
    working_days = models.BooleanField(default=False, help_text="Count offsets in working days.")
    step_name = models.CharField(max_length=200, blank=True)
    repeat_every_days = models.PositiveSmallIntegerField(null=True, blank=True)
    max_repeats = models.PositiveSmallIntegerField(default=0)
    to_main_only = models.BooleanField(default=False)
    description = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["key"], condition=~Q(key=""), name="reminder_schedule_key_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name
