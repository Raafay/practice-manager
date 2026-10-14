"""A client whose status becomes onboarding gets its checklist."""

from django.dispatch import receiver

from apps.clients.models import Client
from apps.clients.services import status_changed

from . import services


@receiver(status_changed, dispatch_uid="onboarding_status_changed")
def on_status_changed(sender, client, old, new, actor=None, **kwargs):
    if new == Client.Status.ONBOARDING:
        services.ensure_checklist(client)
