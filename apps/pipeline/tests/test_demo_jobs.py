import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.tests.factories import manager
from apps.clients.models import Client
from apps.events.models import Notification
from apps.pipeline import jobs, services
from apps.pipeline.models import Proposal, ProspectDetails
from apps.pipeline.tests.helpers import prospect

pytestmark = pytest.mark.django_db


def test_demo_covers_the_pipeline_and_is_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = (Client.objects.count(), Proposal.objects.count(), ProspectDetails.objects.count())
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (
        Client.objects.count(),
        Proposal.objects.count(),
        ProspectDetails.objects.count(),
    )
    open_rows = ProspectDetails.objects.filter(stage__is_open=True, client__status="prospect")
    assert open_rows.count() >= 12
    assert len({d.stage_id for d in open_rows}) >= 6
    assert len(services.quiet_prospects()) >= 2
    assert set(Proposal.objects.values_list("state", flat=True)) >= {
        "sent",
        "viewed",
        "declined",
        "accepted",
    }
    assert ProspectDetails.objects.filter(stage__is_won=True).count() >= 2
    lost = ProspectDetails.objects.filter(stage__is_lost=True)
    assert lost.count() >= 3 and all(d.lost_reason for d in lost)
    assert ProspectDetails.objects.filter(client__meetings__isnull=False).distinct().count() >= 4


def test_the_daily_job_tells_the_owner_once_per_quiet_spell():
    boss = manager()
    c = prospect("Quiet Job Ltd", owner=boss)
    ProspectDetails.objects.filter(client=c).update(
        next_action_date=timezone.localdate() - timedelta(days=2)
    )
    assert jobs.notify_quiet() == 1
    assert jobs.notify_quiet() == 0
    assert Notification.objects.filter(user=boss, kind="quiet_prospect").count() == 1
