"""Tests for findings of the Stage 13 security review that cut across apps.

Each test names its finding in docs/SECURITY-REVIEW.md.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory, owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.comms.tests.factories import client_with_contact, make_template
from apps.services.tests.factories import service

pytestmark = pytest.mark.django_db


@pytest.fixture
def no_fees_user():
    """Staff whose role has had "See client fees" taken away by the owner."""
    role = Role.objects.create(slug="no-fees", name="No fees", order=8, rights=["comms.approve"])
    return UserFactory(role=role)


def _client_with_fee(actor):
    from apps.services import services as service_rules

    client = ClientFactory(client_type="ltd", status="active")
    cs = service_rules.switch_on(
        actor, client, service("bookkeeping"), fee_amount=Decimal("987.65")
    )
    service_rules.change_fee(actor, cs, Decimal("1234.56"), "monthly", reason="New scope")
    return client


# F5: fees in places other than the Fees tab.


def test_the_timeline_shows_no_fee_amounts(client, no_fees_user):
    record = _client_with_fee(owner())
    sign_in(client, no_fees_user)
    page = client.get(reverse("clients:timeline", args=[record.pk])).content.decode()
    assert "987.65" not in page and "1,234.56" not in page and "1234.56" not in page


def test_the_client_summary_pdf_events_carry_no_fees(no_fees_user):
    from apps.events.models import ActivityEvent

    record = _client_with_fee(owner())
    for event in ActivityEvent.objects.filter(client=record):
        assert "987.65" not in event.summary and "1,234.56" not in event.summary


def test_sorting_clients_by_fee_needs_the_right(client, no_fees_user):
    from apps.clients import columns

    assert columns.valid_sort("-monthly_fee", no_fees_user) == ""
    assert columns.valid_sort("-monthly_fee", owner()) == "-monthly_fee"


def test_money_merge_fields_are_hidden_from_a_sender_without_the_right(no_fees_user):
    from apps.comms import services as comms

    record, _ = client_with_contact()
    record.client_type = "ltd"
    record.save()
    from apps.services import services as service_rules

    service_rules.switch_on(owner(), record, service("bookkeeping"), fee_amount=Decimal("321.00"))
    template = make_template(body="<p>Your fee is {{ monthly_fee }} a month.</p>")
    ctx = comms.build_context(record, user=no_fees_user)
    _, html, text, problems = comms.render_template(template, ctx)
    assert "321" not in html and "321" not in text
    assert any("cannot see" in p for p in problems)
    # Someone with the right gets the figure.
    _, html, _, problems = comms.render_template(
        template, comms.build_context(record, user=owner())
    )
    assert "321.00" in html and not problems


def test_a_queued_message_that_shows_fees_is_closed_to_a_role_without_the_right(
    client, no_fees_user
):
    from apps.comms import services as comms

    record, contact = client_with_contact()
    template = make_template(body="<p>Your fee is {{ monthly_fee }}.</p>")
    message = comms.create_message(
        record, template=template, to=contact.email, subject="Fees", body_html="<p>£50.00</p>"
    )
    sign_in(client, no_fees_user)
    assert client.get(reverse("comms:message", args=[message.pk])).status_code == 403
    sign_in(client, staff())
    assert client.get(reverse("comms:message", args=[message.pk])).status_code == 200


def test_proposals_and_letters_need_the_right_to_see_fees(client, no_fees_user):
    record = ClientFactory(status="onboarding")
    sign_in(client, no_fees_user)
    assert client.post(reverse("pipeline:proposal_new", args=[record.pk])).status_code == 403
    assert client.post(reverse("onboarding:prepare", args=[record.pk])).status_code == 403


def test_pipeline_money_totals_are_for_the_owner_only(client):
    sign_in(client, staff())
    page = client.get(reverse("pipeline:prospects")).content.decode()
    assert "Open pipeline a month" not in page
    sign_in(client, owner())
    page = client.get(reverse("pipeline:prospects")).content.decode()
    assert "Open pipeline a month" in page


# F9: a text message cannot be rewritten after approval or sending.


def test_a_sent_text_message_cannot_be_edited(client):
    from apps.comms import services as comms
    from apps.comms.models import Channel, QueuedMessage

    record, _ = client_with_contact()
    message = comms.create_message(
        record, to="07700900123", body_text="Original", channel=Channel.SMS
    )
    QueuedMessage.objects.filter(pk=message.pk).update(state=QueuedMessage.State.SENT)
    sign_in(client, staff())
    client.post(
        reverse("comms:message", args=[message.pk]),
        {"action": "save", "to": "07700900999", "body": "Changed"},
    )
    message.refresh_from_db()
    assert message.body_text == "Original" and message.to == "07700900123"


# F10: retrying a failed message runs the approval checks again.


def test_retry_refuses_a_message_to_a_client_who_has_left():
    from django.core.exceptions import ValidationError

    from apps.comms import services as comms
    from apps.comms.models import QueuedMessage

    record, contact = client_with_contact()
    message = comms.create_message(
        record, to=contact.email, subject="Hello", body_html="<p>Hello</p>"
    )
    QueuedMessage.objects.filter(pk=message.pk).update(state=QueuedMessage.State.FAILED)
    record.status = "former"
    record.save()
    message.refresh_from_db()
    with pytest.raises(ValidationError):
        comms.retry(message, owner())
    message.refresh_from_db()
    assert message.state == QueuedMessage.State.FAILED


def test_the_pause_switch_does_not_redirect_off_site(client):
    sign_in(client, owner())
    response = client.post(reverse("comms:pause"), {"paused": "1", "next": "https://evil.example"})
    assert response["Location"] == reverse("comms:queue")


# F11: the password is asked for again before connecting Xero and the failures download.


@pytest.mark.parametrize("name, args", [("finance:xero_connect", []), ("imports:failures", [1])])
def test_the_password_is_asked_for_again(client, name, args):
    sign_in(client, owner(), recent_password=False)
    response = client.get(reverse(name, args=args))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_reauthenticate"))


# F13: request bodies and files.


def test_a_huge_request_is_refused_before_it_is_read(client):
    response = client.generic("POST", "/r/any-token/", b"x", CONTENT_LENGTH=str(200 * 1024 * 1024))
    assert response.status_code == 413


def test_files_are_never_cached(client):
    from apps.clients.tests.factories import DocumentFactory

    document = DocumentFactory(client=ClientFactory())
    sign_in(client, staff())
    response = client.get(reverse("clients:document_download", args=[document.public_id]))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"


# F14: tax references in an import file are not shown back.


def test_the_match_page_hides_tax_reference_columns(client):
    from apps.imports.tests.helpers import boss, csv_bytes, upload

    run = upload(
        boss(),
        "clients",
        "made-up.csv",
        csv_bytes("Name,Type,Corp Tax UTR,NI Number", "Sample Ltd,Ltd,1234567890,ZZ123456Z"),
    )
    sign_in(client, boss())
    page = client.get(reverse("imports:match", args=[run.pk])).content.decode()
    assert "1234567890" not in page and "ZZ123456Z" not in page
    assert "Sample Ltd" in page


# F15: a reveal is logged only on a client the person is linked to.


def test_a_reveal_cannot_be_filed_on_an_unrelated_client(client):
    from apps.clients.tests.factories import ContactFactory
    from apps.events.models import ActivityEvent

    person = ContactFactory(ni_number="ZZ 12 34 56 Z")
    unrelated = ClientFactory()
    sign_in(client, staff())
    client.post(
        reverse("clients:contact_reveal", args=[person.pk, "ni_number"]),
        {"client": unrelated.pk},
    )
    event = ActivityEvent.objects.filter(verb="sensitive.revealed").latest("pk")
    assert event.client_id is None
