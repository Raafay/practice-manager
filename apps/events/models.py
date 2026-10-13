from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import TimeStampedModel


class EventError(Exception):
    pass


class ActivityEvent(TimeStampedModel):
    """The audit trail and the client timeline. Never edited or deleted.

    Write one only through `apps.events.services.record`.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_label = models.CharField(max_length=200, blank=True)
    verb = models.CharField(max_length=60, db_index=True)
    client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Kept if the client is deleted for good, so the history still says whose it was.
    client_label = models.CharField(max_length=220, blank=True)
    target_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    target_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("target_type", "target_id")
    target_label = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=500)
    data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["client", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%d/%m/%Y %H:%M} {self.verb}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise EventError("Activity events are never changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EventError("Activity events are never deleted.")


class NotificationQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)

    def unread_for(self, user):
        return self.filter(user=user, read_at__isnull=True)


class Notification(TimeStampedModel):
    """A message for one staff member, shown under the bell."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.CharField(max_length=300)
    link = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.message
