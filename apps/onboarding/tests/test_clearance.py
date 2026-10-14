from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientFactory
from apps.comms.models import QueuedMessage
from apps.core.models import PracticeSettings
from apps.onboarding import clearance

pytestmark = pytest.mark.django_db


def start(client=None):
    client = client or ClientFactory(status="onboarding")
    return clearance.start(
        manager(),
        client,
        accountant_name="Alex Previous",
        email="alex@example.com",
        firm="Previous & Co",
        asked_for=["last_accounts", "tax_returns"],
    )


def test_clearance_queues_an_email_with_a_pdf_copy_and_the_list():
    request = start()
    message = request.message
    assert message.state == "needs_approval" and message.to == "alex@example.com"
    assert "Last accounts" in message.body_html and "Tax returns" in message.body_html
    assert "Trial balance" not in message.body_html
    assert request.letter_document.content_type == "application/pdf"
    assert list(message.attachments.all()) == [request.letter_document]
    assert request.letter_document.client == request.client
    assert request.sent_on == timezone.localdate()


def test_chase_is_offered_only_after_fourteen_days_and_only_once():
    request = start()
    today = timezone.localdate()
    assert not clearance.chase_due(request, today + timedelta(days=13))
    assert clearance.chase_due(request, today + timedelta(days=14))
    clearance.chase(manager(), request)
    assert request.chase_message.state == "needs_approval"
    assert not clearance.chase_due(request, today + timedelta(days=30))
    with pytest.raises(Exception, match="already been chased"):
        clearance.chase(manager(), request)


def test_a_reply_ends_the_chase_prompt():
    request = start()
    clearance.update(
        manager(),
        request,
        received=["last_accounts"],
        reply_received_on=date(2026, 10, 20),
        notes="",
    )
    assert not clearance.chase_due(request, date(2027, 1, 1))
    assert request.received == ["last_accounts"]


def test_clearance_pages(client):
    c = ClientFactory(status="onboarding")
    sign_in(client, staff())
    assert client.get(reverse("onboarding:clearance_start", args=[c.pk])).status_code == 200
    response = client.post(
        reverse("onboarding:clearance_start", args=[c.pk]),
        {
            "accountant_name": "Alex Previous",
            "email": "alex@example.com",
            "asked_for": ["last_accounts"],
        },
    )
    assert response.status_code == 302
    assert QueuedMessage.objects.filter(client=c, reason="Professional clearance request").exists()
    page = client.get(reverse("onboarding:tab", args=[c.pk])).content.decode()
    assert "Alex Previous" in page
    client.logout()
    assert client.get(reverse("onboarding:clearance_start", args=[c.pk])).status_code == 302


# ---------------------------------------------------------------- retention (item 9)


def test_former_client_gets_retention_dates_from_the_settings():
    practice = PracticeSettings.load()
    practice.retention_years = 7
    practice.aml_retention_years = 4
    practice.save()
    target = ClientFactory(status="active")
    client_services.change_status(owner(), target, "former", ended_on=date(2026, 3, 31))
    target.refresh_from_db()
    assert target.relationship_ended_on == date(2026, 3, 31)
    assert target.retain_until == date(2033, 3, 31)
    assert target.aml_retain_until == date(2030, 3, 31)
