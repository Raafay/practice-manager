"""Builders for the finance tests. Everything is invented."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.pipeline import services as pipeline_services
from apps.pipeline.models import PipelineStage, Proposal, ProspectDetails
from apps.services.models import ClientService, Service


def aware(day: date, hour: int = 12) -> datetime:
    return timezone.make_aware(datetime.combine(day, time(hour)))


def give_service(client, code, amount, frequency="monthly", *, state="active", starts=None, ends=None):
    return ClientService.objects.create(
        client=client,
        service=Service.objects.get(code=code),
        state=state,
        fee_amount=Decimal(str(amount)),
        fee_frequency=frequency,
        starts_on=starts,
        ends_on=ends,
    )


def live_client(name, code, amount, frequency="monthly", *, since=None, ends=None, **fields):
    client = ClientFactory(name=name, status=Client.Status.ACTIVE, client_since=since, **fields)
    give_service(client, code, amount, frequency, starts=since, ends=ends)
    return client


def prospect(name, fee, stage_key, *, start=None, last_activity=None):
    client = ClientFactory(name=name, status=Client.Status.PROSPECT)
    details = pipeline_services.ensure_details(client)
    details.stage = PipelineStage.objects.get(key=stage_key)
    details.expected_fee = Decimal(str(fee))
    details.expected_start = start
    details.last_activity_at = last_activity
    details.save()
    return client


def decided(won, lost, today):
    """Prospects won and lost in the last twelve months."""
    for i in range(won + lost):
        client = ClientFactory(status=Client.Status.LOST if i >= won else Client.Status.ACTIVE)
        details = pipeline_services.ensure_details(client)
        day = today - timedelta(days=30 + i)
        if i < won:
            details.won_on = day
        else:
            details.lost_on = day
        details.save()


def sent_proposal(client, monthly, sent_on):
    return Proposal.objects.create(
        client=client,
        state=Proposal.State.SENT,
        monthly_total=Decimal(str(monthly)),
        valid_until=sent_on + timedelta(days=30),
        sent_at=aware(sent_on),
    )
