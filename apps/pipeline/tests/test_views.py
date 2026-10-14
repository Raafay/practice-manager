import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.core import ratelimit
from apps.core.models import ActionLink
from apps.pipeline import proposals
from apps.pipeline.models import Proposal, ProspectDetails
from apps.pipeline.tests.helpers import no_fee_staff, propose, prospect, stage
from apps.pipeline.tests.test_proposals import sent_proposal, token_for, with_services

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    client, proposal, link = sent_proposal()
    return {"c": client, "p": proposal}


def staff_addresses(w):
    c, p = w["c"].pk, w["p"].pk
    return [
        ("pipeline:prospects", [], "get"),
        ("pipeline:prospect_new", [], "get"),
        ("pipeline:prospect_new", [], "post"),
        ("pipeline:move", [c], "get"),
        ("pipeline:move", [c], "post"),
        ("pipeline:sales_edit", [c], "get"),
        ("pipeline:sales_edit", [c], "post"),
        ("pipeline:meeting_add", [c], "get"),
        ("pipeline:meeting_add", [c], "post"),
        ("pipeline:proposal_new", [c], "post"),
        ("pipeline:proposal", [c, p], "get"),
        ("pipeline:proposal_send", [c, p], "get"),
        ("pipeline:proposal_send", [c, p], "post"),
        ("pipeline:proposal_withdraw", [c, p], "post"),
        ("pipeline:proposal_cancel_link", [c, p], "post"),
    ]


def settings_addresses(w):
    st = stage("enquiry").pk
    return [
        ("pipeline:stages", [], "get"),
        ("pipeline:stage_add", [], "get"),
        ("pipeline:stage_add", [], "post"),
        ("pipeline:stage_edit", [st], "get"),
        ("pipeline:stage_edit", [st], "post"),
        ("pipeline:stage_delete", [st], "post"),
        ("pipeline:rules", [], "get"),
        ("pipeline:rules", [], "post"),
    ]


def call(client, name, args, method):
    return getattr(client, method)(reverse(name, args=args))


def test_every_address_sends_signed_out_users_to_sign_in(client, world):
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        response = call(client, name, args, method)
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_every_address_refuses_portal_users(client, world):
    sign_in(client, portal_user())
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_settings_need_the_settings_right(client, world):
    sign_in(client, staff())
    for name, args, method in settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_a_proposal_under_the_wrong_client_is_not_found(client, world):
    sign_in(client, owner())
    other = ClientFactory()
    for name in ("pipeline:proposal", "pipeline:proposal_send"):
        assert client.get(reverse(name, args=[other.pk, world["p"].pk])).status_code == 404


# ---- the Prospects page


def test_the_board_and_list_show_prospects(client):
    prospect("Boardy Ltd", stage_key="follow_up", fee="250")
    sign_in(client, manager())
    board = client.get(reverse("pipeline:prospects"))
    assert board.status_code == 200 and b"Boardy Ltd" in board.content
    assert "£250.00" in board.content.decode()
    listing = client.get(reverse("pipeline:prospects") + "?view=list&sort=-fee")
    assert b"Boardy Ltd" in listing.content


def test_filters_narrow_the_board(client):
    boss = manager()
    prospect("Mine Ltd", owner=boss)
    prospect("Other Ltd", owner=staff())
    sign_in(client, boss)
    page = client.get(reverse("pipeline:prospects") + f"?owner={boss.pk}")
    assert b"Mine Ltd" in page.content and b"Other Ltd" not in page.content


def test_fees_are_absent_without_the_fees_right(client):
    prospect("Costly Ltd", fee="777", stage_key="follow_up")
    sign_in(client, no_fee_staff())
    page = client.get(reverse("pipeline:prospects"))
    html = page.content.decode()
    assert "Costly Ltd" in html and "777" not in html
    assert "a month" not in html and "Open pipeline" not in html
    listing = client.get(reverse("pipeline:prospects") + "?view=list").content.decode()
    assert "777" not in listing and "Monthly fee" not in listing


def test_the_weighted_value_is_for_the_owner_only(client):
    prospect("Weighty Ltd", fee="500", stage_key="meeting_held")
    sign_in(client, manager())
    assert b"Weighted a month" not in client.get(reverse("pipeline:prospects")).content
    sign_in(client, owner())
    assert b"Weighted a month" in client.get(reverse("pipeline:prospects")).content


def test_the_client_page_hides_the_fee_without_the_right(client):
    c = prospect("Info Ltd", fee="888")
    sign_in(client, no_fee_staff())
    html = client.get(reverse("clients:detail", args=[c.pk])).content.decode()
    assert "Sales" in html
    # Standalone only: random tokens on the page (CSRF, ids) can contain the digits.
    assert not re.search(r"(?<![A-Za-z0-9])888(?![0-9A-Za-z])", html)


def test_an_empty_board_says_what_to_do(client):
    sign_in(client, manager())
    page = client.get(reverse("pipeline:prospects"))
    assert b"No prospects yet" in page.content


# ---- dragging


def test_dragging_to_lost_without_a_reason_is_refused(client):
    c = prospect("Drag Ltd")
    sign_in(client, manager())
    url = reverse("pipeline:move", args=[c.pk])
    response = client.post(url, {"to": stage("lost").pk}, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 422
    c.refresh_from_db()
    assert c.status == Client.Status.PROSPECT and not c.prospect.stage.is_lost


def test_dragging_to_lost_with_a_reason_works(client):
    c = prospect("Drag2 Ltd")
    sign_in(client, manager())
    response = client.post(
        reverse("pipeline:move", args=[c.pk]), {"to": stage("lost").pk, "lost_reason": "price"}
    )
    assert response.status_code == 302
    c.refresh_from_db()
    assert c.status == Client.Status.LOST and c.prospect.lost_reason == "price"


def test_the_lost_and_won_prompts_open(client):
    c = prospect("Prompt Ltd")
    sign_in(client, manager())
    lost = client.get(reverse("pipeline:move", args=[c.pk]) + f"?to={stage('lost').pk}")
    assert b"Why was it lost" in lost.content
    won = client.get(reverse("pipeline:move", args=[c.pk]) + f"?to={stage('won').pk}")
    assert b"Onboarding starts" in won.content


def test_won_needs_confirming_and_then_starts_onboarding(client):
    c = prospect("Winner Ltd")
    sign_in(client, manager())
    url = reverse("pipeline:move", args=[c.pk])
    assert client.post(url, {"to": stage("won").pk}).status_code == 422
    assert client.post(url, {"to": stage("won").pk, "confirm": "1"}).status_code == 302
    c.refresh_from_db()
    assert c.status == Client.Status.ONBOARDING


def test_an_ordinary_drag_returns_the_card(client):
    c = prospect("Card Ltd", fee="10")
    sign_in(client, manager())
    response = client.post(
        reverse("pipeline:move", args=[c.pk]),
        {"to": stage("follow_up").pk},
        headers={"X-Requested-With": "fetch"},
    )
    assert response.status_code == 200 and b"Card Ltd" in response.content
    c.prospect.refresh_from_db()
    assert c.prospect.stage.key == "follow_up"


def test_only_prospects_can_be_moved(client):
    active = ClientFactory(status="active")
    sign_in(client, manager())
    assert (
        client.post(reverse("pipeline:move", args=[active.pk]), {"to": stage("won").pk}).status_code
        == 404
    )


def test_a_next_redirect_cannot_leave_the_site(client):
    c = prospect("Redirect Ltd")
    sign_in(client, manager())
    response = client.post(
        reverse("pipeline:move", args=[c.pk]),
        {"to": stage("follow_up").pk, "next": "https://evil.example/"},
    )
    assert response["Location"] == reverse("pipeline:prospects")


# ---- forms


def test_a_new_prospect_needs_a_name_and_a_way_to_reach_them(client):
    sign_in(client, manager())
    url = reverse("pipeline:prospect_new")
    bad = client.post(url, {"name": "Reachless Ltd", "client_type": "ltd"})
    assert bad.status_code == 422
    ok = client.post(
        url,
        {
            "name": "Reachable Ltd",
            "client_type": "ltd",
            "phone": "01632 960001",
            "expected_fee": "50",
        },
    )
    assert ok.status_code == 302
    made = Client.objects.get(name="Reachable Ltd")
    assert made.status == "prospect" and made.prospect.expected_fee == 50


def test_editing_sales_details_and_logging_a_meeting(client):
    boss = manager()
    c = prospect("Edit Ltd")
    sign_in(client, boss)
    response = client.post(
        reverse("pipeline:sales_edit", args=[c.pk]),
        {
            "owner": boss.pk,
            "source": "website",
            "next_action": "Ring them",
            "next_action_date": "2026-11-01",
            "expected_start": "2026-12-15",
        },
    )
    assert response.status_code == 302
    c.refresh_from_db()
    c.prospect.refresh_from_db()
    assert c.source == "website" and c.prospect.next_action == "Ring them"
    assert c.prospect.expected_start.day == 1
    meeting = client.post(
        reverse("pipeline:meeting_add", args=[c.pk]),
        {
            "on_date": "2026-10-10",
            "at_time": "10:30",
            "kind": "video",
            "follow_up": "Send prices",
            "follow_up_date": "2026-10-20",
        },
    )
    assert meeting.status_code == 302 and c.meetings.count() == 1
    assert c.meetings.get().follow_up_task is not None


def test_the_engagement_tab_lists_proposals_and_the_info_tab_has_the_sales_panel(client, world):
    sign_in(client, manager())
    tab = client.get(reverse("onboarding:engagement", args=[world["c"].pk]))
    assert b"Version 1" in tab.content and b"Proposals" in tab.content
    info = client.get(reverse("clients:detail", args=[world["c"].pk]))
    assert b"Sales" in info.content and b"Meetings" in info.content


def test_the_compose_window_sends_a_proposal(client):
    c = with_services("Compose Ltd")
    boss = manager()
    sign_in(client, boss)
    proposal = proposals.create_proposal(boss, c)
    url = reverse("pipeline:proposal_send", args=[c.pk, proposal.pk])
    page = client.get(url)
    assert page.status_code == 200 and b"Send Proposal Email" in page.content
    form = page.context["form"]
    response = client.post(
        url,
        {
            "contacts": ["pat@example.com"],
            "cc": "",
            "subject": form.initial["subject"],
            "body": form.initial["body"],
            "show_breakdown": "on",
            "show_vat_text": "on",
            "signature": "mine",
            "action": "send",
        },
    )
    assert response.status_code == 302
    proposal.refresh_from_db()
    assert proposal.state == "sent"


def test_a_proposal_cannot_be_sent_without_the_link(client):
    c = with_services("NoLink Ltd")
    boss = manager()
    sign_in(client, boss)
    proposal = proposals.create_proposal(boss, c)
    response = client.post(
        reverse("pipeline:proposal_send", args=[c.pk, proposal.pk]),
        {
            "contacts": ["pat@example.com"],
            "subject": "Hello",
            "body": "<p>No link here</p>",
            "signature": "mine",
            "action": "send",
        },
    )
    assert response.status_code == 422 and b"proposal link" in response.content
    proposal.refresh_from_db()
    assert proposal.state == "draft"


def test_the_overview_shows_quiet_prospects(client):
    boss = manager()
    c = prospect("Dormant Ltd", owner=boss)
    ProspectDetails.objects.filter(client=c).update(
        next_action_date=timezone.localdate() - timedelta(days=3)
    )
    sign_in(client, boss)
    page = client.get(reverse("overview"))
    assert b"Quiet prospects" in page.content and b"Dormant Ltd" in page.content


# ---- the proposal page, reached without signing in


def page_url(token):
    return reverse("pipeline:proposal_page", args=[token])


def test_the_page_works_without_signing_in_and_marks_it_viewed(client, world):
    link, token = token_for(world["p"])
    response = client.get(page_url(token))
    assert response.status_code == 200
    html = response.content.decode()
    assert world["c"].name in html and "Accept" in html
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    world["p"].refresh_from_db()
    assert world["p"].state == "viewed"


def test_a_wrong_token_gets_a_plain_message(client, world):
    for token in ("not-a-real-token", "x" * 200, "a" * 43):
        response = client.get(page_url(token))
        assert response.status_code == 404
        assert b"This link is not available" in response.content
        assert world["c"].name.encode() not in response.content


def test_a_cancelled_or_expired_link_shows_a_plain_message(client, world):
    link, token = token_for(world["p"])
    link.cancelled_at = timezone.now()
    link.save()
    response = client.get(page_url(token))
    assert response.status_code == 404 and b"This link is not available" in response.content
    link.cancelled_at = None
    link.expires_at = timezone.now() - timedelta(minutes=1)
    link.save()
    response = client.get(page_url(token))
    assert response.status_code == 404 and b"This link is not available" in response.content
    assert world["c"].name.encode() not in response.content


def test_a_withdrawn_proposal_link_stops_working(client, world):
    link, token = token_for(world["p"])
    proposals.withdraw(manager(), world["p"])
    ActionLink.objects.filter(pk=link.pk).update(cancelled_at=None)
    assert client.get(page_url(token)).status_code == 404


def test_the_page_shows_nothing_about_any_other_client(client, world):
    other_client, other_proposal, _ = sent_proposal(with_services("Secret Other Ltd"))
    link, token = token_for(world["p"])
    html = client.get(page_url(token)).content.decode()
    assert "Secret Other Ltd" not in html and other_client.name not in html
    # The staff address for the other proposal is closed to a signed-out visitor.
    staff_url = reverse("pipeline:proposal", args=[other_client.pk, other_proposal.pk])
    assert client.get(staff_url).status_code == 302
    # A link for one proposal cannot decide another.
    client.post(page_url(token), {"action": "accept", "agree": "on", "typed_name": "Pat Prospect"})
    other_proposal.refresh_from_db()
    assert other_proposal.state == "sent"


def test_accepting_online(client, world):
    link, token = token_for(world["p"])
    response = client.post(
        page_url(token), {"action": "accept", "agree": "on", "typed_name": "Pat Prospect"}
    )
    assert response.status_code == 200 and b"Accepted by Pat Prospect" in response.content
    world["p"].refresh_from_db()
    world["c"].refresh_from_db()
    assert world["p"].state == "accepted" and world["c"].status == "onboarding"
    assert b"Accept the proposal" not in response.content  # nothing more can be done
    again = client.post(page_url(token), {"action": "decline", "reason": "changed my mind"})
    assert again.status_code == 422 and b"already been made" in again.content
    world["p"].refresh_from_db()
    assert world["p"].state == "accepted"


def test_accepting_needs_the_tick_and_a_name(client, world):
    link, token = token_for(world["p"])
    response = client.post(page_url(token), {"action": "accept", "typed_name": "Pat Prospect"})
    assert response.status_code == 422
    world["p"].refresh_from_db()
    assert world["p"].state != "accepted"


def test_declining_online_and_asking_a_question(client, world):
    link, token = token_for(world["p"])
    asked = client.post(page_url(token), {"action": "question", "question": "Is VAT included?"})
    assert asked.status_code == 200 and b"We have your question" in asked.content
    assert world["c"].notes.filter(text__contains="Is VAT included?").exists()
    declined = client.post(page_url(token), {"action": "decline", "reason": "Too dear"})
    assert declined.status_code == 200 and b"declined" in declined.content
    world["p"].refresh_from_db()
    assert world["p"].state == "declined"
    world["c"].refresh_from_db()
    assert world["c"].status == Client.Status.PROSPECT


def test_the_pdf_download_needs_the_token(client, world):
    link, token = token_for(world["p"])
    response = client.get(reverse("pipeline:proposal_pdf", args=[token]))
    assert response.status_code == 200 and response["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response["Content-Disposition"]
    assert client.get(reverse("pipeline:proposal_pdf", args=["wrong"])).status_code == 404


def test_the_page_is_rate_limited(client, world):
    link, token = token_for(world["p"])
    for _ in range(10):
        client.post(page_url(token), {"action": "question", "question": ""})
    response = client.post(page_url(token), {"action": "question", "question": ""})
    assert response.status_code == 429
    ratelimit.reset("proposal-ip:127.0.0.1")


def test_the_page_needs_a_csrf_token_when_enforced(world):
    from django.test import Client as TestClient

    link, token = token_for(world["p"])
    strict = TestClient(enforce_csrf_checks=True)
    response = strict.post(
        page_url(token), {"action": "accept", "agree": "on", "typed_name": "Pat"}
    )
    assert response.status_code == 403
    world["p"].refresh_from_db()
    assert world["p"].state != "accepted"


def test_staff_can_see_the_state_of_a_proposal(client, world):
    sign_in(client, manager())
    page = client.get(reverse("pipeline:proposal", args=[world["c"].pk, world["p"].pk]))
    assert page.status_code == 200 and b"Fingerprint" in page.content
    _ = (propose, Proposal)
