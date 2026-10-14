import hashlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.tests.factories import manager, staff
from apps.clients.models import Client, Note
from apps.comms.models import QueuedMessage
from apps.core import actionlinks
from apps.core.models import ActionLink, PracticeSettings
from apps.events.models import ActivityEvent
from apps.pipeline import proposals, services
from apps.pipeline.models import Proposal
from apps.pipeline.tests.helpers import propose, prospect

pytestmark = pytest.mark.django_db


def with_services(name="Proposed Ltd", **kw):
    client = prospect(name, stage_key="follow_up", owner=manager(), **kw)
    propose(client, manager(), ("accounts", "100", "monthly"), ("vat", "300", "quarterly"))
    return client


def sent_proposal(client=None):
    client = client or with_services()
    boss = manager()
    proposal = proposals.create_proposal(boss, client)
    subject, html = proposals.default_message(proposal, boss)
    proposals.send_proposal(boss, proposal, to="pat@example.com", subject=subject, body_html=html)
    proposal.refresh_from_db()
    link = ActionLink.objects.get(purpose="proposal", object_id=proposal.pk)
    return client, proposal, link


def token_for(proposal):
    ActionLink.objects.filter(purpose="proposal", object_id=proposal.pk).delete()
    link, token = actionlinks.create(
        purpose="proposal",
        contact=proposal.contact,
        client=proposal.client,
        object_id=proposal.pk,
        expires_at=timezone.now() + timedelta(days=10),
    )
    return link, token


# ---- totals: each combination of the three switches, with a quarterly fee


def shown(vat_registered, breakdown, inc_vat, vat_text):
    practice = PracticeSettings.load()
    practice.vat_registered, practice.vat_rate = vat_registered, Decimal("20.00")
    practice.save()
    client = with_services()
    proposal = proposals.create_proposal(manager(), client)
    proposal.show_breakdown, proposal.show_inc_vat, proposal.show_vat_text = (
        breakdown,
        inc_vat,
        vat_text,
    )
    proposal.save()
    return proposals.view_model(proposal)


def test_the_monthly_total_converts_a_quarterly_fee():
    client = with_services()
    proposal = proposals.create_proposal(manager(), client)
    assert proposal.monthly_total == Decimal("200.00")  # 100 monthly + 300 / 3


@pytest.mark.parametrize(
    ("registered", "breakdown", "inc_vat", "vat_text", "monthly", "line"),
    [
        (True, True, False, True, "£200.00 +VAT", "£300.00 +VAT per quarter"),
        (True, True, False, False, "£200.00", "£300.00 per quarter"),
        (True, True, True, True, "£240.00 inc. VAT", "£360.00 inc. VAT per quarter"),
        (True, True, True, False, "£240.00 inc. VAT", "£360.00 inc. VAT per quarter"),
        (True, False, False, True, "£200.00 +VAT", None),
        (True, False, True, False, "£240.00 inc. VAT", None),
        (False, True, True, True, "£200.00", "£300.00 per quarter"),
        (False, False, False, False, "£200.00", None),
    ],
)
def test_fee_display_follows_the_three_switches(
    registered, breakdown, inc_vat, vat_text, monthly, line
):
    vm = shown(registered, breakdown, inc_vat, vat_text)
    assert vm["monthly_text"] == monthly
    texts = [r["fee_text"] for r in vm["recurring"]]
    if line is None:
        html = proposals.render_body(vm["proposal"])
        assert "per quarter" not in html and "£300" not in html
        assert "Accounts" in html
    else:
        assert line in texts


def test_a_setup_fee_and_one_off_fees_are_shown_apart_from_the_monthly_charge():
    client = with_services()
    propose(client, manager(), ("payroll", "50", "one_off"))
    client.prospect.setup_fee = Decimal("150")
    client.prospect.save()
    proposal = proposals.create_proposal(manager(), client)
    vm = proposals.view_model(proposal)
    assert proposal.monthly_total == Decimal("200.00")
    assert vm["setup_text"].startswith("£150.00")
    assert vm["one_off_text"].startswith("£50.00")


def test_the_email_summary_follows_the_switches():
    client = with_services()
    proposal = proposals.create_proposal(manager(), client)
    proposal.show_breakdown = False
    proposal.save()
    html, text = proposals.summary_block(proposal)
    assert "Monthly charge" in text and "per quarter" not in text


# ---- making, versions, sending


def test_a_proposal_copies_the_proposed_services_and_fees():
    client = with_services()
    proposal = proposals.create_proposal(manager(), client)
    assert [(line["code"], line["fee"], line["frequency"]) for line in proposal.lines] == [
        ("accounts", "100.00", "monthly"),
        ("vat", "300.00", "quarterly"),
    ]
    assert proposal.version == 1 and proposal.state == "draft"
    assert proposal.valid_until == timezone.localdate() + timedelta(days=30)
    assert "Starter text" in proposal.what_next_html


def test_a_proposal_needs_services():
    client = prospect("Empty Ltd")
    with pytest.raises(ValidationError):
        proposals.create_proposal(manager(), client)


def test_a_new_version_withdraws_the_old_one_and_kills_its_link():
    client, first, link = sent_proposal()
    second = proposals.create_proposal(manager(), client)
    first.refresh_from_db()
    link.refresh_from_db()
    assert second.version == 2 and first.state == "withdrawn"
    assert link.cancelled_at is not None
    assert actionlinks.resolve("anything", "proposal") is None


def test_changing_the_services_is_flagged_as_needing_a_new_version():
    client, proposal, _ = sent_proposal()
    assert not proposals.services_changed_since(proposal)
    propose(client, manager(), ("payroll", "40", "monthly"))
    assert proposals.services_changed_since(proposal)


def test_sending_queues_one_message_approved_by_the_sender_and_sets_the_stage():
    client, proposal, link = sent_proposal()
    message = proposal.message
    assert message.state == QueuedMessage.State.APPROVED and message.approved_by is not None
    assert proposal.state == "sent" and proposal.sent_at
    client.prospect.refresh_from_db()
    assert client.prospect.stage.key == "proposal_sent"
    assert proposal.document is not None
    pdf = proposal.document.file.read()
    assert proposal.fingerprint == hashlib.sha256(pdf).hexdigest()
    # The placeholder address was swapped for a real, working link.
    assert "proposal.invalid" not in message.body_html
    assert "/proposal/" in message.body_html
    assert ActivityEvent.objects.filter(client=client, verb="proposal.sent").exists()


def test_nothing_is_emailed_by_sending_alone():
    sent_proposal()
    assert mail.outbox == []


def test_a_user_who_cannot_approve_queues_it_for_approval():
    from apps.accounts.models import Role

    role = Role.objects.get(slug=Role.STAFF)
    role.rights = []
    role.save()
    client = with_services("Needs Approval Ltd")
    low = staff()
    proposal = proposals.create_proposal(low, client)
    subject, html = proposals.default_message(proposal, low)
    proposals.send_proposal(low, proposal, to="pat@example.com", subject=subject, body_html=html)
    proposal.refresh_from_db()
    assert proposal.message.state == QueuedMessage.State.NEEDS_APPROVAL


def test_the_message_must_keep_the_link():
    client = with_services()
    proposal = proposals.create_proposal(manager(), client)
    with pytest.raises(ValidationError, match="link"):
        proposals.send_proposal(
            manager(), proposal, to="pat@example.com", subject="Hi", body_html="<p>No link</p>"
        )
    assert proposal.state == "draft"


def test_the_link_lasts_until_the_valid_until_date():
    _, proposal, link = sent_proposal()
    local = timezone.localtime(link.expires_at)
    assert local.date() == proposal.valid_until + timedelta(days=1) and local.hour == 0


# ---- the client's side


def test_opening_the_page_marks_it_viewed_once():
    client, proposal, _ = sent_proposal()
    link, token = token_for(proposal)
    proposals.note_viewed(proposal, link)
    proposal.refresh_from_db()
    first = proposal.viewed_at
    assert proposal.state == "viewed" and first
    proposals.note_viewed(proposal, link)
    proposal.refresh_from_db()
    assert proposal.viewed_at == first
    assert ActivityEvent.objects.filter(client=client, verb="proposal.viewed").count() == 1


def test_accepting_moves_stage_and_status_and_leaves_services_proposed():
    client, proposal, link = sent_proposal()
    proposals.accept(link, typed_name="Pat Prospect", agreed=True, ip="203.0.113.5", agent="Test")
    proposal.refresh_from_db()
    client.refresh_from_db()
    client.prospect.refresh_from_db()
    assert proposal.state == "accepted" and proposal.decided_by == "Pat Prospect"
    assert proposal.ip_address == "203.0.113.5" and proposal.user_agent == "Test"
    assert client.status == Client.Status.ONBOARDING
    assert client.prospect.stage.is_won and client.prospect.won_on == timezone.localdate()
    assert set(client.client_services.values_list("state", flat=True)) == {"proposed"}
    assert client.onboarding_items.filter(key="proposal_accepted", state="done").exists()


def test_accepting_saves_a_pdf_with_the_acceptance_details_to_documents():
    client, proposal, link = sent_proposal()
    proposals.accept(link, typed_name="Pat Prospect", agreed=True, ip="203.0.113.5", agent="Test")
    proposal.refresh_from_db()
    document = proposal.accepted_document
    assert document is not None and document.client == client
    assert document.file.read().startswith(b"%PDF")


def test_accepting_notifies_the_owner_and_the_manager():
    from apps.events.models import Notification

    client, proposal, link = sent_proposal()
    proposals.accept(link, typed_name="Pat Prospect", agreed=True, ip=None, agent="")
    assert Notification.objects.filter(message__contains="accepted the proposal").exists()


def test_acceptance_needs_the_tick_and_a_name():
    _, _, link = sent_proposal()
    with pytest.raises(ValidationError):
        proposals.accept(link, typed_name="Pat Prospect", agreed=False, ip=None, agent="")
    with pytest.raises(ValidationError):
        proposals.accept(link, typed_name="P", agreed=True, ip=None, agent="")


def test_the_decision_can_be_made_only_once():
    _, _, link = sent_proposal()
    proposals.accept(link, typed_name="Pat Prospect", agreed=True, ip=None, agent="")
    with pytest.raises(ValidationError, match="already"):
        proposals.accept(link, typed_name="Pat Prospect", agreed=True, ip=None, agent="")
    with pytest.raises(ValidationError):
        proposals.decline(link, reason="", ip=None, agent="")


def test_declining_changes_the_state_and_leaves_the_prospect_where_it_was():
    client, proposal, link = sent_proposal()
    client.prospect.refresh_from_db()
    stage_before = client.prospect.stage_id
    assert client.prospect.stage.key == "proposal_sent"
    proposals.decline(link, reason="Too dear", ip=None, agent="")
    proposal.refresh_from_db()
    client.refresh_from_db()
    client.prospect.refresh_from_db()
    assert proposal.state == "declined" and proposal.decline_reason == "Too dear"
    assert client.status == Client.Status.PROSPECT
    assert client.prospect.stage_id == stage_before


def test_a_question_becomes_a_note_and_tells_the_owner():
    from apps.events.models import Notification

    client, proposal, link = sent_proposal()
    note = proposals.ask_question(link, text="Does the fee include VAT returns?")
    assert isinstance(note, Note) and note.client == client
    assert "Does the fee include VAT returns?" in note.text
    assert Notification.objects.filter(message__contains="asked a question").exists()
    proposal.refresh_from_db()
    assert proposal.state in ("sent", "viewed")  # a question does not decide anything


def test_overdue_proposals_expire_and_their_links_stop_working():
    from apps.pipeline.jobs import pipeline_daily  # noqa: F401

    client, proposal, link = sent_proposal()
    Proposal.objects.filter(pk=proposal.pk).update(
        valid_until=timezone.localdate() - timedelta(days=1)
    )
    assert proposals.expire_overdue() == 1
    proposal.refresh_from_db()
    link.refresh_from_db()
    assert proposal.state == "expired" and link.cancelled_at is not None
    assert proposals.expire_overdue() == 0


def test_withdrawing_cancels_the_link():
    _, proposal, link = sent_proposal()
    proposals.withdraw(manager(), proposal)
    link.refresh_from_db()
    assert link.cancelled_at is not None


def test_on_proposal_accepted_can_be_called_on_its_own():
    client = prospect("Direct Ltd", stage_key="proposal_sent")
    proposals.on_proposal_accepted(client)
    client.refresh_from_db()
    assert client.status == Client.Status.ONBOARDING
    assert services.ensure_details(client).stage.is_won
