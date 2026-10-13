"""Helpers for service tests. Everything here is invented."""

from datetime import date

from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.services.models import ClientService, Service


def service(code: str) -> Service:
    return Service.objects.get(code=code)


def take(client: Client, code: str, *, starts_on: date | None = date(2026, 1, 1), **kwargs):
    """Give a client a service in state active, without going through the switch-on rules."""
    kwargs.setdefault("fee_amount", None)
    return ClientService.objects.create(
        client=client,
        service=service(code),
        state=kwargs.pop("state", ClientService.State.ACTIVE),
        starts_on=starts_on,
        **kwargs,
    )


def company(**kwargs) -> Client:
    return ClientFactory(**kwargs)
