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
