"""Builders for the pipeline tests. Everything is invented."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Role
from apps.clients.models import Client
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.pipeline import services
from apps.pipeline.models import PipelineStage
from apps.services import services as svc
from apps.services.models import Service


def stage(key: str) -> PipelineStage:
    return PipelineStage.objects.get(key=key)


def prospect(name="Sample Prospect Ltd", *, stage_key="enquiry", fee=None, owner=None, **fields):
    client = ClientFactory(name=name, status=Client.Status.PROSPECT, **fields)
    contact = ContactFactory(first_name="Pat", last_name="Prospect", email="pat@example.com")
    ClientContactFactory(client=client, contact=contact, is_main=True, can_sign=True)
    details = services.ensure_details(client)
    details.stage = stage(stage_key)
    details.owner = owner
    details.stage_changed_at = timezone.now()
    if fee is not None:
        details.expected_fee = Decimal(fee)
    details.save()
    return client


def propose(client, actor, *pairs):
    """Tick services as proposed. pairs are (service code, fee, frequency)."""
    for code, fee, frequency in pairs:
        service = Service.objects.get(code=code)
        cs = svc.switch_on(actor, client, service, fee_amount=Decimal(fee))
        cs.fee_frequency = frequency
        cs.save()
    return client


def no_fee_staff():
    """A staff user whose role cannot see fees."""
    from apps.accounts.tests.factories import staff

    role = Role.objects.get(slug=Role.STAFF)
    role.rights = [r for r in role.rights if r != "fees.view"]
    role.save()
    return staff()


def long_ago(days):
    return timezone.now() - timedelta(days=days)
