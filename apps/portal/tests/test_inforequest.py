"""Information requests: only missing fields, secure link, postal route, apply, reminders."""

import re
from datetime import date, timedelta

import pytest
from django.test import Client as Browser
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, sign_in, staff
from apps.clients.models import ClientContact
from apps.clients.tests.factories import ClientFactory, ContactFactory
from apps.comms.models import QueuedMessage
from apps.events.models import ActivityEvent
from apps.portal import inforequest
from apps.portal.models import InfoRequest
from apps.portal.tests.helpers import pdf_upload, portal_login, portal_person

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    client = ClientFactory(name="Alpha Ltd", manager=manager())
    contact = ContactFactory(mobile="07700 900000")
    ClientContact.objects.create(client=client, contact=contact, is_main=True, roles=["director"])
    return client, contact


def token_from(message) -> str:
    return re.search(r"/i/([^/\"]+)/", message.body_html).group(1)


def test_only_empty_fields_are_asked(world):
    client, contact = world
    contact.ni_number = "QQ123456C"
    contact.save()
    gaps = inforequest.missing(client, contact)
    assert "ni_number" not in gaps and "phone" not in gaps and "email" not in gaps
    assert {"personal_utr", "dob", "home_address", "company_utr", "ch_auth_code"} <= set(gaps)


def test_company_only_fields_are_not_asked_of_a_sole_trader(world):
    client, contact = world
    client.client_type = "sole_trader"
    client.save()
    assert "company_utr" not in inforequest.missing(client, contact)


def test_email_request_is_queued_for_approval_and_never_sent_direct(world):
    client, contact = world
    info = inforequest.create(staff(), client, contact, channel="email")
    message = QueuedMessage.objects.get(client=client)
    assert message.state == QueuedMessage.State.NEEDS_APPROVAL
    assert "/i/" in message.body_html
    assert info.state == "waiting"
    assert ActivityEvent.objects.filter(verb="info_request.created", client=client).exists()


def test_the_link_shows_only_missing_fields_and_saves_the_reply(world):
    client, contact = world
    info = inforequest.create(staff(), client, contact, channel="email")
    token = token_from(QueuedMessage.objects.get(client=client))
    contact.date_of_birth = date(1980, 1, 1)
    contact.save()
    browser = Browser()
    page = browser.get(reverse("portal:info_form", args=[token]))
    assert page.status_code == 200
    html = page.content.decode()
    assert 'name="personal_utr"' in html
    assert 'name="dob"' not in html  # filled since the request was made
    assert page["X-Robots-Tag"]
    response = browser.post(
        reverse("portal:info_form", args=[token]),
        {
            "personal_utr": "12345 67890",
            "home_address": "1 Made Up Street\nZZ1 1ZZ",
            "files": pdf_upload(),
        },
    )
    assert response.status_code == 200
    info.refresh_from_db()
    assert info.state == "answered"
    assert info.answers["personal_utr"].startswith("enc:")
    assert "1234567890" not in str(info.answers)
    assert info.request.files.count() == 1
    # The record is untouched until staff apply it.
    contact.refresh_from_db()
    assert contact.personal_utr == ""
    # The link works once.
    assert browser.get(reverse("portal:info_form", args=[token])).status_code == 404


def test_bad_values_are_refused_and_secrets_not_echoed(world):
    client, contact = world
    inforequest.create(staff(), client, contact, channel="email")
    token = token_from(QueuedMessage.objects.get(client=client))
    response = Browser().post(
        reverse("portal:info_form", args=[token]),
        {"personal_utr": "123", "ni_number": "AB123456C9", "dob": "2999-01-01"},
    )
    assert response.status_code == 422
    html = response.content.decode()
    assert "A UTR is ten digits." in html
    assert "AB123456C9" not in html


def test_wrong_cancelled_or_expired_links_are_404(world):
    client, contact = world
    info = inforequest.create(staff(), client, contact, channel="email")
    token = token_from(QueuedMessage.objects.get(client=client))
    assert Browser().get(reverse("portal:info_form", args=["nope"])).status_code == 404
    info.expires_at = timezone.now() - timedelta(minutes=1)
    info.save()
    from apps.core.models import ActionLink

    ActionLink.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert Browser().get(reverse("portal:info_form", args=[token])).status_code == 404


def test_cancelling_stops_the_link(world):
    client, contact = world
    info = inforequest.create(staff(), client, contact, channel="email")
    token = token_from(QueuedMessage.objects.get(client=client))
    inforequest.cancel(staff(), info)
    assert Browser().get(reverse("portal:info_form", args=[token])).status_code == 404


def test_staff_apply_ticked_answers_to_the_record(client, world):
    cl, contact = world
    info = inforequest.create(staff(), cl, contact, channel="email")
    token = token_from(QueuedMessage.objects.get(client=cl))
    Browser().post(
        reverse("portal:info_form", args=[token]),
        {"personal_utr": "1234567890", "dob": "1980-04-30", "ch_auth_code": "abc123"},
    )
    sign_in(client, manager())
    page = client.get(reverse("portal:info_detail", args=[cl.pk, info.pk])).content.decode()
    assert "1234567890" not in page  # masked
    client.post(
        reverse("portal:info_apply", args=[cl.pk, info.pk]),
        {"apply": ["personal_utr", "ch_auth_code"]},
    )
    contact.refresh_from_db()
    cl.refresh_from_db()
    assert contact.personal_utr == "1234567890"
    assert cl.ch_auth_code == "ABC123"
    assert contact.date_of_birth is None  # not ticked
    info.refresh_from_db()
    assert info.state == "done" and info.answers == {}
    event = ActivityEvent.objects.get(verb="info_request.applied")
    assert "1234567890" not in str(event.__dict__)


def test_postal_route_prints_a_form_and_staff_type_in_the_reply(client, world):
    cl, contact = world
    sign_in(client, manager())
    response = client.post(
        reverse("portal:info_new", args=[cl.pk]), {"contact": contact.pk, "channel": "post"}
    )
    assert response.status_code == 302
    info = InfoRequest.objects.get()
    assert not QueuedMessage.objects.exists()
    pdf = client.get(reverse("portal:info_pdf", args=[cl.pk, info.pk]))
    assert pdf["Content-Type"] == "application/pdf"
    assert ActivityEvent.objects.filter(verb="info_request.printed").exists()
    client.post(reverse("portal:info_enter", args=[cl.pk, info.pk]), {"ni_number": "QQ 12 34 56 C"})
    info.refresh_from_db()
    assert info.state == "answered"
    client.post(reverse("portal:info_apply", args=[cl.pk, info.pk]), {"apply": ["ni_number"]})
    contact.refresh_from_db()
    assert contact.ni_number == "QQ123456C"


def test_reminders_after_7_and_14_days(world):
    cl, contact = world
    info = inforequest.create(staff(), cl, contact, channel="email")
    assert inforequest.send_reminders() == 0
    InfoRequest.objects.filter(pk=info.pk).update(sent_at=timezone.now() - timedelta(days=8))
    assert inforequest.send_reminders() == 1
    assert inforequest.send_reminders() == 0  # once each
    InfoRequest.objects.filter(pk=info.pk).update(sent_at=timezone.now() - timedelta(days=15))
    assert inforequest.send_reminders() == 1
    reminders = QueuedMessage.objects.filter(subject__startswith="Reminder")
    assert reminders.count() == 2
    assert all(m.state == QueuedMessage.State.NEEDS_APPROVAL for m in reminders)


def test_postal_reminder_tells_the_sender(world):
    cl, contact = world
    sender = staff()
    info = inforequest.create(sender, cl, contact, channel="post")
    InfoRequest.objects.filter(pk=info.pk).update(sent_at=timezone.now() - timedelta(days=8))
    inforequest.send_reminders()
    assert sender.notifications.filter(message__contains=info.reference).exists()


def test_nothing_missing_means_nothing_to_ask(world):
    cl, contact = world
    with pytest.raises(Exception, match="Nothing is missing"):
        inforequest.create(staff(), cl, contact, channel="email", fields=["nonsense"])


def test_staff_pages_refuse_signed_out_and_portal_users(client, world):
    cl, contact = world
    info = inforequest.create(staff(), cl, contact, channel="post")
    urls = [
        ("get", reverse("portal:info_new", args=[cl.pk])),
        ("get", reverse("portal:info_detail", args=[cl.pk, info.pk])),
        ("get", reverse("portal:info_pdf", args=[cl.pk, info.pk])),
        ("get", reverse("portal:info_enter", args=[cl.pk, info.pk])),
        ("post", reverse("portal:info_apply", args=[cl.pk, info.pk])),
        ("post", reverse("portal:info_cancel", args=[cl.pk, info.pk])),
    ]
    for method, url in urls:
        response = getattr(client, method)(url)
        assert response.status_code == 302 and "/login/" in response["Location"], url
    user, _, _ = portal_person(cl, main=False)
    portal_login(client, user)
    for method, url in urls:
        assert getattr(client, method)(url).status_code == 403, url


def test_a_request_cannot_be_opened_under_another_client(client, world):
    cl, contact = world
    info = inforequest.create(staff(), cl, contact, channel="post")
    sign_in(client, manager())
    other = ClientFactory()
    assert client.get(reverse("portal:info_detail", args=[other.pk, info.pk])).status_code == 404


def test_the_tab_and_inbox_are_called_client_requests(client, world):
    cl, contact = world
    inforequest.create(staff(), cl, contact, channel="post")
    sign_in(client, manager())
    inbox = client.get(reverse("portal:inbox")).content.decode()
    assert "Client requests" in inbox and contact.full_name in inbox
    tab = client.get(reverse("portal:client_requests", args=[cl.pk])).content.decode()
    assert "Ask for missing details" in tab
