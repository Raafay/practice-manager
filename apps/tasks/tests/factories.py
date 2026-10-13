"""Helpers for task tests. Everything here is invented."""

from datetime import date

from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.services import deadlines
from apps.services.tests.factories import take
from apps.tasks import services
from apps.tasks.models import Task, TaskCategory, TaskKind, TaskStatus

TODAY = date(2026, 10, 12)


def status(name: str) -> TaskStatus:
    return TaskStatus.objects.get(name=name)


def category(name: str) -> TaskCategory:
    return TaskCategory.objects.get(name=name)


def accounts_client(**kwargs) -> Client:
    """A company with the Accounts service and its deadline and tasks made."""
    kwargs.setdefault("next_accounts_made_up_to", date(2026, 12, 31))
    kwargs.setdefault("next_accounts_due", date(2027, 9, 30))
    client = ClientFactory(**kwargs)
    take(client, "accounts")
    deadlines.generate_for_client(client, today=TODAY)
    return client


def make_task(actor=None, **kwargs) -> Task:
    kwargs.setdefault("title", "Advice call")
    kwargs.setdefault("kind", TaskKind.ADVISORY)
    return services.create_task(actor, **kwargs)
