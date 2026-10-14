"""Delivery reports from the email provider (Stage 13, item 5). Every value is made up."""

import base64
import json

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import sign_in, staff
from apps.comms import services
from apps.comms.models import QueuedMessage
from apps.comms.tests.factories import client_with_contact
from apps.events.models import ActivityEvent, Notification

pytestmark = pytest.mark.django_db

SECRET = "made-up-hook:made-up-password-0123456789"


def _auth(secret=SECRET):
    return {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(secret.encode()).decode()}


@pytest.fixture
def sent_message():
    record, contact = client_with_contact()
    approver = staff()
    message = services.create_message(
        record, to=contact.email, subject="Your VAT return", body_html="<p>Hello</p>"
    )
    QueuedMessage.objects.filter(pk=message.pk).update(
        state=QueuedMessage.State.SENT, provider_message_id="made-up-id-001", approved_by=approver
    )
    message.refresh_from_db()
    return message


@pytest.fixture
def postmark(settings):
    settings.EMAIL_PROVIDER = "postmark"
    settings.ANYMAIL = {"WEBHOOK_SECRET": SECRET, "POSTMARK_SERVER_TOKEN": "made-up"}


def _postmark(client, payload, **extra):
    return client.post(
        reverse("comms:webhook"), json.dumps(payload), content_type="application/json", **extra
    )


def test_a_bounce_is_recorded_and_the_approver_is_told(client, postmark, sent_message):
    payload = {
        "RecordType": "Bounce",
        "Type": "HardBounce",
        "MessageID": "made-up-id-001",
        "Email": "pat.sample@example.com",
        "BouncedAt": "2026-10-14T10:00:00Z",
        "Description": "The address does not exist.",
    }
    response = _postmark(client, payload, **_auth())
    assert response.status_code == 200
    sent_message.refresh_from_db()
    assert sent_message.delivery_state == "bounced"
    assert ActivityEvent.objects.filter(verb="message.bounced", client=sent_message.client).exists()
    note = Notification.objects.get(user=sent_message.approved_by)
    assert "bounced" in note.message
    # The same report twice changes nothing more.
    _postmark(client, payload, **_auth())
    assert Notification.objects.filter(user=sent_message.approved_by).count() == 1


def test_a_delivery_is_recorded(client, postmark, sent_message):
    payload = {
        "RecordType": "Delivery",
        "MessageID": "made-up-id-001",
        "Recipient": "pat.sample@example.com",
        "DeliveredAt": "2026-10-14T10:00:00Z",
    }
    assert _postmark(client, payload, **_auth()).status_code == 200
    sent_message.refresh_from_db()
    assert sent_message.delivery_state == "delivered"


def test_a_report_without_the_secret_is_refused(client, postmark, sent_message):
    payload = {"RecordType": "Bounce", "MessageID": "made-up-id-001", "Type": "HardBounce"}
    assert _postmark(client, payload).status_code in (400, 403)
    assert _postmark(client, payload, **_auth("made-up-hook:wrong")).status_code in (400, 403)
    sent_message.refresh_from_db()
    assert sent_message.delivery_state == ""


def test_amazon_ses_reports_through_sns(client, settings, sent_message):
    settings.EMAIL_PROVIDER = "ses"
    settings.ANYMAIL = {"WEBHOOK_SECRET": SECRET}
    ses_event = {
        "eventType": "Bounce",
        "bounce": {
            "bounceType": "Permanent",
            "bounceSubType": "General",
            "bouncedRecipients": [{"emailAddress": "pat.sample@example.com"}],
            "timestamp": "2026-10-14T10:00:00.000Z",
        },
        "mail": {
            "messageId": "made-up-id-001",
            "timestamp": "2026-10-14T09:59:00.000Z",
            "destination": ["pat.sample@example.com"],
        },
    }
    sns = {
        "Type": "Notification",
        "MessageId": "made-up-sns-id",
        "TopicArn": "arn:aws:sns:eu-west-2:000000000000:made-up-topic",
        "Message": json.dumps(ses_event),
        "Timestamp": "2026-10-14T10:00:01.000Z",
    }
    response = client.post(
        reverse("comms:webhook"),
        json.dumps(sns),
        content_type="text/plain; charset=UTF-8",
        HTTP_X_AMZ_SNS_MESSAGE_TYPE="Notification",
        HTTP_X_AMZ_SNS_MESSAGE_ID="made-up-sns-id",
        HTTP_X_AMZ_SNS_TOPIC_ARN="arn:aws:sns:eu-west-2:000000000000:made-up-topic",
        **_auth(),
    )
    assert response.status_code == 200
    sent_message.refresh_from_db()
    assert sent_message.delivery_state == "bounced"


def test_without_a_provider_there_is_no_webhook(client):
    assert (
        client.post(reverse("comms:webhook"), "{}", content_type="application/json").status_code
        == 404
    )


def test_the_queued_page_shows_bounces(client, sent_message):
    from apps.comms import delivery

    delivery.record("made-up-id-001", "bounced")
    sign_in(client, staff())
    page = client.get(reverse("comms:queue")).content.decode()
    assert "bounced or" in page and "?delivery=problem" in page
    page = client.get(reverse("comms:queue") + "?delivery=problem").content.decode()
    assert "Bounced: check the address" in page
    assert "Your VAT return" in page
