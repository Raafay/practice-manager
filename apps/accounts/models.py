import hashlib
import hmac
import secrets
from datetime import timedelta
from decimal import Decimal

from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import TimeStampedModel, validate_hex_colour

from .rights import RIGHTS, check_right


class LastOwnerError(ValidationError):
    def __init__(self):
        super().__init__("There must always be one active owner. Make someone else owner first.")


class Role(TimeStampedModel):
    OWNER = "owner"
    MANAGER = "manager"
    STAFF = "staff"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=50)
    rights = models.JSONField(default=list, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_owner_role(self) -> bool:
        return self.slug == self.OWNER

    def has(self, right: str) -> bool:
        check_right(right)
        return self.is_owner_role or right in self.rights

    def effective_rights(self) -> set[str]:
        return set(RIGHTS) if self.is_owner_role else set(self.rights) & set(RIGHTS)


class Team(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserQuerySet(models.QuerySet):
    def staff(self):
        return self.filter(kind=User.Kind.STAFF)

    def active_owners(self):
        return self.filter(kind=User.Kind.STAFF, is_active=True, role__slug=Role.OWNER)


class UserManager(BaseUserManager.from_queryset(UserQuerySet)):
    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().select_related("role")

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", Role.objects.get(slug=Role.OWNER))
        extra.setdefault("kind", User.Kind.STAFF)
        return self.create_user(email, password, **extra)


def default_initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class User(AbstractBaseUser, TimeStampedModel):
    class Kind(models.TextChoices):
        STAFF = "staff", "Staff"
        PORTAL = "portal", "Portal"

    email = models.EmailField("email address", unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.STAFF)
    name = models.CharField(max_length=150)
    initials = models.CharField(
        max_length=2, blank=True, help_text="Two letters, shown in avatars."
    )
    colour = models.CharField(max_length=7, default="#64748b", validators=[validate_hex_colour])
    job_title = models.CharField(max_length=100, blank=True)
    role = models.ForeignKey(
        Role, on_delete=models.PROTECT, null=True, blank=True, related_name="users"
    )
    teams = models.ManyToManyField(Team, blank=True, related_name="members")
    weekly_hours = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("37.5"))
    email_signature = models.TextField(blank=True)
    email_overdue = models.BooleanField("overdue tasks", default=True)
    email_today = models.BooleanField("tasks due today", default=True)
    email_week = models.BooleanField("tasks due this week", default=True)
    extra_rights = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_ci_unique")]

    def __str__(self) -> str:
        return self.name or self.email

    # Kinds and roles

    @property
    def is_staff_kind(self) -> bool:
        return self.kind == self.Kind.STAFF

    @property
    def is_portal(self) -> bool:
        return self.kind == self.Kind.PORTAL

    @property
    def is_owner(self) -> bool:
        return bool(self.is_active and self.is_staff_kind and self.role and self.role.is_owner_role)

    @property
    def is_staff(self) -> bool:
        """Used by Django's admin. Only the owner may use it (see ControlAdminSite)."""
        return self.is_owner

    def has_perm(self, perm, obj=None) -> bool:
        return self.is_owner

    def has_module_perms(self, app_label) -> bool:
        return self.is_owner

    # Rights

    def can(self, right: str) -> bool:
        """True if this user holds the right through their role or a single grant."""
        check_right(right)
        if not (self.is_active and self.is_staff_kind):
            return False
        if self.role and self.role.has(right):
            return True
        return right in (self.extra_rights or [])

    def effective_rights(self) -> set[str]:
        if not (self.is_active and self.is_staff_kind):
            return set()
        from_role = self.role.effective_rights() if self.role else set()
        return from_role | (set(self.extra_rights or []) & set(RIGHTS))

    # Two-factor

    @property
    def mfa_done(self) -> bool:
        """Staff must have an authenticator app set up before they can use anything."""
        return Authenticator.objects.filter(user=self, type=Authenticator.Type.TOTP).exists()

    @property
    def display_initials(self) -> str:
        return (self.initials or default_initials(self.name) or self.email[:2]).upper()

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).lower()

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        if not self.initials:
            self.initials = default_initials(self.name)
        if self.pk and not self._state.adding:
            self._guard_last_owner()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_owner and not User.objects.active_owners().exclude(pk=self.pk).exists():
            raise LastOwnerError()
        return super().delete(*args, **kwargs)

    def _guard_last_owner(self) -> None:
        stored = User.objects.filter(pk=self.pk).values("is_active", "kind", "role__slug").first()
        if not stored:
            return
        was_owner = (
            stored["is_active"]
            and stored["kind"] == self.Kind.STAFF
            and stored["role__slug"] == Role.OWNER
        )
        others = User.objects.active_owners().exclude(pk=self.pk)
        if was_owner and not self.is_owner and not others.exists():
            raise LastOwnerError()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class InvitationQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(
            accepted_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=timezone.now()
        )


class Invitation(TimeStampedModel):
    """An invitation for a new staff member. Only the hash of its token is stored."""

    email = models.EmailField()
    name = models.CharField(max_length=150)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="invitations")
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation for {self.email}"

    @classmethod
    def issue(cls, *, email: str, name: str, role: Role, invited_by) -> tuple["Invitation", str]:
        raw = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            email=email.strip().lower(),
            name=name.strip(),
            role=role,
            invited_by=invited_by,
            token_hash=hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=settings.INVITATION_VALID_HOURS),
        )
        return invitation, raw

    @classmethod
    def from_token(cls, raw: str) -> "Invitation | None":
        if not raw or len(raw) > 100:
            return None
        digest = hash_token(raw)
        invitation = cls.objects.filter(token_hash=digest).select_related("role").first()
        if invitation is None or not hmac.compare_digest(invitation.token_hash, digest):
            return None
        return invitation

    @property
    def state(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.cancelled_at:
            return "cancelled"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"

    @property
    def is_usable(self) -> bool:
        return self.state == "pending"
