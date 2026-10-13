from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel, validate_hex_colour

ALERT_DEADLINE_DAYS = 7
DEADLINE_SOON_DAYS = 14


class TaskStatus(TimeStampedModel):
    name = models.CharField(max_length=60, unique=True)
    colour = models.CharField(max_length=7, default="#64748b", validators=[validate_hex_colour])
    position = models.PositiveIntegerField(default=0)
    is_done = models.BooleanField(default=False)
    is_waiting = models.BooleanField("waiting on the client", default=False)
    is_default = models.BooleanField("new tasks start here", default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "task statuses"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="one_default_status"
            )
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def default(cls) -> "TaskStatus":
        return (
            cls.objects.filter(is_default=True).first()
            or cls.objects.filter(active=True, is_done=False).first()
            or cls.objects.first()
        )

    @classmethod
    def done_status(cls) -> "TaskStatus":
        return (
            cls.objects.filter(is_done=True, active=True).first()
            or cls.objects.filter(is_done=True).first()
        )


class TaskKind(models.TextChoices):
    COMPLIANCE = "compliance", "Compliance"
    ADVISORY = "advisory", "Fractional"
    REQUEST = "request", "Request"
    ONBOARDING = "onboarding", "Onboarding"
    SALES = "sales", "Sales"
    INTERNAL = "internal", "Internal"


class TaskCategory(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=12, choices=TaskKind.choices, default=TaskKind.COMPLIANCE)
    colour = models.CharField(max_length=7, default="#64748b", validators=[validate_hex_colour])
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "task categories"

    def __str__(self) -> str:
        return self.name


class TaskTemplate(TimeStampedModel):
    """What a deadline of a given service and rule turns into: one task, with steps."""

    class Owner(models.TextChoices):
        MANAGER = "manager", "Client manager"
        PARTNER = "partner", "Client partner"
        USER = "user", "A named person"
        NOBODY = "nobody", "Unassigned"

    class Target(models.TextChoices):
        DAYS_BEFORE_DUE = "days_before_due", "Days before the due date"
        WORKING_DAYS_BEFORE_DUE = "working_days_before_due", "Working days before the due date"
        DAYS_BEFORE_CT_PAYMENT = (
            "days_before_ct_payment",
            "Days before the corporation tax payment date",
        )
        FIXED_DAY = "fixed_day", "A fixed day of the year before the due date"

    service = models.ForeignKey(
        "services.Service", on_delete=models.CASCADE, related_name="task_templates"
    )
    rule = models.CharField(max_length=40)
    name_pattern = models.CharField(
        max_length=200,
        help_text="Use {period_end}, {period_label} and {due_date}.",
    )
    category = models.ForeignKey(
        TaskCategory, on_delete=models.PROTECT, null=True, blank=True, related_name="templates"
    )
    default_owner = models.CharField(max_length=10, choices=Owner.choices, default=Owner.MANAGER)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    target_kind = models.CharField(
        max_length=24, choices=Target.choices, default=Target.DAYS_BEFORE_DUE
    )
    target_days = models.PositiveSmallIntegerField(default=0)
    target_month = models.PositiveSmallIntegerField(null=True, blank=True)
    target_day = models.PositiveSmallIntegerField(null=True, blank=True)
    estimate_minutes = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["service__position", "position", "id"]

    def __str__(self) -> str:
        return f"{self.name_pattern} ({self.service})"

    def clean(self):
        if self.target_kind == self.Target.FIXED_DAY and not (
            self.target_month and self.target_day
        ):
            raise ValidationError("Give the month and the day for a fixed date.")
        if self.default_owner == self.Owner.USER and not self.owner_user_id:
            raise ValidationError("Choose the person who owns these tasks.")


class TaskTemplateStep(TimeStampedModel):
    template = models.ForeignKey(TaskTemplate, on_delete=models.CASCADE, related_name="steps")
    name = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    stops_reminders = models.BooleanField(default=False)
    is_filing = models.BooleanField("filing step", default=False)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name


class TaskQuerySet(models.QuerySet):
    def live(self):
        return self.filter(cancelled_at__isnull=True)

    def open(self):
        return self.live().filter(status__is_done=False)


class Task(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Source(models.TextChoices):
        GENERATED = "generated", "Generated"
        MANUAL = "manual", "Manual"
        REQUEST = "request", "Request"
        REPEATING = "repeating", "Repeating"
        PROJECT_TEMPLATE = "project_template", "Project template"

    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)  # cleaned HTML
    client = models.ForeignKey(
        "clients.Client", on_delete=models.CASCADE, null=True, blank=True, related_name="tasks"
    )
    contact = models.ForeignKey(
        "clients.Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=12, choices=TaskKind.choices, default=TaskKind.COMPLIANCE)
    category = models.ForeignKey(
        TaskCategory, on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    service = models.ForeignKey(
        "services.Service", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    deadline = models.ForeignKey(
        "services.Deadline", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    status = models.ForeignKey(TaskStatus, on_delete=models.PROTECT, related_name="tasks")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_tasks",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_tasks",
    )
    team = models.ForeignKey(
        "accounts.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    followers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="followed_tasks"
    )
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    target_date = models.DateField(null=True, blank=True, db_index=True)
    start_date = models.DateField(null=True, blank=True)
    period_label = models.CharField(max_length=100, blank=True)
    estimate_minutes = models.PositiveIntegerField(null=True, blank=True)
    # Stage 8 turns these three into links to projects, sections and repeating tasks.
    project_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    section_id = models.PositiveBigIntegerField(null=True, blank=True)
    repeating_task_id = models.PositiveBigIntegerField(null=True, blank=True)
    position = models.FloatField(default=0)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["deadline", "template"],
                condition=Q(deadline__isnull=False, template__isnull=False),
                name="one_task_per_deadline_template",
            )
        ]
        indexes = [models.Index(fields=["owner", "status"], name="task_owner_status")]

    def __str__(self) -> str:
        return self.title

    @property
    def is_done(self) -> bool:
        return self.status.is_done

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    @property
    def is_open(self) -> bool:
        return not self.is_done and not self.is_cancelled

    def alert(self, today: date | None = None) -> bool:
        """Target date passed, or the deadline within seven days, and not done."""
        if not self.is_open:
            return False
        today = today or timezone.localdate()
        if self.target_date and self.target_date < today:
            return True
        return bool(self.due_date and self.due_date <= today + timedelta(days=ALERT_DEADLINE_DAYS))

    def deadline_tone(self, today: date | None = None) -> str:
        """red if overdue, amber within 14 days, grey otherwise."""
        if not self.due_date:
            return "neutral"
        today = today or timezone.localdate()
        if self.is_open and self.due_date < today:
            return "red"
        if self.is_open and self.due_date <= today + timedelta(days=DEADLINE_SOON_DAYS):
            return "amber"
        return "neutral"

    @property
    def latest_action(self) -> str:
        """The last step ticked. Uses prefetched steps when there are any."""
        ticked = [s for s in self.steps.all() if s.done_at]
        if not ticked:
            return ""
        return max(ticked, key=lambda s: (s.done_at, s.pk)).name


class TaskStep(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="steps")
    name = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    stops_reminders = models.BooleanField(default=False)
    is_filing = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_done(self) -> bool:
        return self.done_at is not None


class TaskComment(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    body = models.TextField()

    class Meta:
        ordering = ["created_at", "id"]


class TaskStar(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="stars")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_stars"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["task", "user"], name="one_star_each")]


class TaskDocument(TimeStampedModel):
    """A client document attached to a task. The file stays under the Document's own rules."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    document = models.ForeignKey(
        "clients.Document", on_delete=models.CASCADE, related_name="task_links"
    )
    attached_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["task", "document"], name="one_link_each")]
