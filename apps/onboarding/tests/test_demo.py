import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.aml.models import RiskAssessment
from apps.clients.models import Client
from apps.onboarding import hmrc
from apps.onboarding.models import EngagementLetter

pytestmark = pytest.mark.django_db


def test_demo_covers_onboarding_aml_and_authorisations_and_is_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = (
        RiskAssessment.objects.count(),
        EngagementLetter.objects.count(),
        Client.objects.count(),
    )
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (
        RiskAssessment.objects.count(),
        EngagementLetter.objects.count(),
        Client.objects.count(),
    )
    # Three clients part-way through onboarding, at different points.
    names = ["Harbour Bakes Ltd", "Quill and Pixel Ltd", "Meadow Fields Partnership"]
    done = []
    for name in names:
        client = Client.objects.get(name=name)
        assert client.status == "onboarding"
        done.append(client.onboarding_items.filter(state="done").count())
    assert done[0] < done[1] < done[2]
    # One high-risk assessment waiting for approval.
    waiting = RiskAssessment.objects.filter(state="submitted")
    assert waiting.count() == 1 and waiting.get().level == "high"
    # A spread of levels and review dates among live clients.
    approved = RiskAssessment.objects.filter(state="approved")
    assert {a.level for a in approved} == {"low", "medium", "high"}
    today = timezone.localdate()
    assert any(a.next_review_due < today for a in approved)
    assert any(today <= a.next_review_due <= today + timedelta(days=30) for a in approved)
    # Authorisations about to expire.
    assert hmrc.expiring().count() >= 2
