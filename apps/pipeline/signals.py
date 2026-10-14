"""A status change made on the client page keeps the sales stage in line."""

from django.dispatch import receiver

from apps.clients.models import Client
from apps.clients.services import status_changed

from . import services


@receiver(status_changed, sender=Client, dispatch_uid="pipeline_status_changed")
def on_status_changed(sender, client, old, new, actor=None, **kwargs):
    services.sync_from_status(client, old, new, actor)
