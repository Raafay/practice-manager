"""Keep deadlines in step with the client: dates, settings, services and status."""

from django.dispatch import receiver

from apps.clients.models import Client
from apps.clients.services import client_updated, status_changed
from apps.companieshouse.services import client_synced

from . import deadlines, services


@receiver(client_updated, dispatch_uid="services_client_updated")
def on_client_updated(sender, client, actor=None, **kwargs):
    deadlines.generate_for_client(client, actor=actor)


@receiver(status_changed, dispatch_uid="services_status_changed")
def on_status_changed(sender, client, old, new, actor=None, **kwargs):
    if new == Client.Status.ACTIVE:
        services.activate_proposed(client, actor)
        deadlines.generate_for_client(client, actor=actor)


@receiver(client_synced, dispatch_uid="services_client_synced")
def on_client_synced(sender, client, result=None, **kwargs):
    deadlines.generate_for_client(client)
