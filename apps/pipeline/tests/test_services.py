from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.tests.factories import manager, staff
from apps.clients.models import Client
from apps.events.models import ActivityEvent
from apps.pipeline import services
from apps.pipeline.models import PipelineSettings, PipelineStage, ProspectDetails
from apps.pipeline.tests.helpers import long_ago, propose, prospect, stage
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def test_stages_are_seeded_with_their_chances():
    chances = {s.name: s.chance for s in PipelineStage.objects.all()}
    assert chances == {
        "Enquiry": 10,
        "Meeting booked": 20,
        "Meeting held": 35,
        "Follow-up": 45,
        "Proposal sent": 60,
        "Won": 100,
        "Lost": 0,
        "On hold": 5,
    }


def test_weighted_pipeline_value_for_a_small_set_of_prospects():
    prospect("A Ltd", stage_key="enquiry", fee="100")  # 10
    prospect("B Ltd", stage_key="meeting_held", fee="200")  # 70
    prospect("C Ltd", stage_key="proposal_sent", fee="333.33")  # 199.998 -> 200.00
    prospect("D Ltd", stage_key="on_hold", fee="1000")  # 50
    figures = services.header_figures(services.board_rows({}))
    assert figures["open_value"] == Decimal("1633.33")
    assert figures["weighted_value"] == Decimal("330.00")
    assert figures["open_count"] == 4


def test_expected_fee_is_the_proposed_services_or_the_hand_figure():
    client = prospect("E Ltd", fee="75")
    assert services.expected_monthly(client) == Decimal("75.00")
    propose(client, manager(), ("accounts", "120", "monthly"), ("vat", "300", "quarterly"))
    assert services.expected_monthly(client) == Decimal("220.00")


# ---- the quiet rule: each condition on its own


def quiet(client, today=None):
    return services.is_quiet(ProspectDetails.objects.get(client=client), today)


def test_a_fresh_prospect_is_not_quiet():
    assert not quiet(prospect("Fresh Ltd"))


def test_a_passed_next_action_date_makes_it_quiet():
    client = prospect("Late Ltd")
    ProspectDetails.objects.filter(client=client).update(
        next_action_date=timezone.localdate() - timedelta(days=1), last_activity_at=timezone.now()
    )
    assert quiet(client)


def test_a_next_action_due_today_is_not_quiet():
    client = prospect("Today Ltd")
    ProspectDetails.objects.filter(client=client).update(next_action_date=timezone.localdate())
    assert not quiet(client)


def test_fourteen_days_with_nothing_happening_makes_it_quiet():
    client = prospect("Idle Ltd")
    ProspectDetails.objects.filter(client=client).update(
        last_activity_at=long_ago(20), created_at=long_ago(30)
    )
    assert quiet(client)


def test_the_number_of_days_is_a_setting():
    client = prospect("Setting Ltd")
    ProspectDetails.objects.filter(client=client).update(
        last_activity_at=long_ago(5), created_at=long_ago(30)
    )
    assert not quiet(client)
    row = PipelineSettings.load()
    row.quiet_days = 3
    row.save()
    assert quiet(client)


def test_on_hold_is_never_quiet():
    client = prospect("Hold Ltd", stage_key="on_hold")
    ProspectDetails.objects.filter(client=client).update(
        next_action_date=timezone.localdate() - timedelta(days=30),
        last_activity_at=long_ago(60),
        created_at=long_ago(90),
    )
    assert not quiet(client)


def test_won_and_lost_are_never_quiet():
    for key in ("won", "lost"):
        client = prospect(f"{key} Ltd", stage_key=key)
        ProspectDetails.objects.filter(client=client).update(
            next_action_date=timezone.localdate() - timedelta(days=30)
        )
        assert not quiet(client)


@pytest.mark.parametrize("what", ["meeting", "note", "task", "touch"])
def test_activity_resets_the_clock(what):
    from apps.clients.models import Note
    from apps.tasks.services import create_task

    boss = manager()
    client = prospect(f"Active {what} Ltd", owner=boss)
    ProspectDetails.objects.filter(client=client).update(
        last_activity_at=long_ago(20), created_at=long_ago(30)
    )
    assert quiet(client)
    if what == "meeting":
        services.log_meeting(boss, client, held_at=timezone.now(), kind="phone")
    elif what == "note":
        Note.objects.create(client=client, text="Rang them", author=boss)
    elif what == "task":
        task = create_task(boss, title="Chase", client=client, kind="sales", owner=boss)
        Task.objects.filter(pk=task.pk).update(completed_at=timezone.now())
    else:
        services.touch(client)
    assert not quiet(client)


def test_a_sent_proposal_or_stage_change_resets_the_clock():
    client = prospect("Moves Ltd")
    ProspectDetails.objects.filter(client=client).update(
        last_activity_at=long_ago(20), created_at=long_ago(30)
    )
    services.move_stage(manager(), client, stage("follow_up"))
    assert not quiet(client)


def test_quiet_prospects_for_one_user_are_their_own():
    boss, other = manager(), staff()
    mine = prospect("Mine Ltd", owner=other)
    theirs = prospect("Theirs Ltd", owner=boss)
    for client in (mine, theirs):
        ProspectDetails.objects.filter(client=client).update(
            next_action_date=timezone.localdate() - timedelta(days=2)
        )
    names = {d.client.name for d in services.quiet_prospects(other)}
    assert names == {"Mine Ltd"}


# ---- moving between stages


def test_lost_needs_a_reason_and_marks_the_client_lost():
    client = prospect("Losing Ltd")
    with pytest.raises(ValidationError):
        services.move_stage(manager(), client, stage("lost"))
    services.move_stage(manager(), client, stage("lost"), lost_reason="price", lost_note="Too dear")
    client.refresh_from_db()
    details = client.prospect
    assert client.status == Client.Status.LOST
    assert details.lost_reason == "price" and details.lost_on == timezone.localdate()


def test_a_lost_prospect_can_come_back():
    client = prospect("Back Ltd")
    services.move_stage(manager(), client, stage("lost"), lost_reason="timing")
    services.move_stage(manager(), client, stage("follow_up"))
    client.refresh_from_db()
    assert client.status == Client.Status.PROSPECT
    assert client.prospect.lost_reason == ""


def test_won_starts_onboarding_and_cannot_go_back():
    client = prospect("Winning Ltd")
    services.move_stage(manager(), client, stage("won"))
    client.refresh_from_db()
    assert client.status == Client.Status.ONBOARDING
    assert client.onboarding_items.exists()
    with pytest.raises(ValidationError):
        services.move_stage(manager(), client, stage("enquiry"))


def test_a_status_change_on_the_client_page_keeps_the_stage_in_line():
    from apps.clients import services as client_services

    client = prospect("Hand Ltd")
    client_services.set_status(manager(), client, Client.Status.LOST)
    client.prospect.refresh_from_db()
    assert client.prospect.stage.is_lost and client.prospect.lost_reason == "other"
    client_services.set_status(manager(), client, Client.Status.PROSPECT)
    client.prospect.refresh_from_db()
    assert client.prospect.stage.key == "enquiry"


def test_moving_is_logged_on_the_timeline():
    client = prospect("Logged Ltd")
    services.move_stage(manager(), client, stage("meeting_booked"))
    assert ActivityEvent.objects.filter(client=client, verb="prospect.stage_changed").exists()


# ---- meetings


def test_a_follow_up_makes_a_sales_task_for_the_owner():
    boss = manager()
    client = prospect("Follow Ltd", owner=boss)
    meeting = services.log_meeting(
        staff(),
        client,
        held_at=timezone.now(),
        kind="face_to_face",
        follow_up="Send prices",
        follow_up_date=timezone.localdate() + timedelta(days=3),
    )
    task = meeting.follow_up_task
    assert task.kind == "sales" and task.owner == boss and task.client == client
    details = client.prospect
    details.refresh_from_db()
    assert details.next_action == "Send prices"


def test_a_meeting_without_a_follow_up_makes_no_task():
    client = prospect("NoTask Ltd")
    services.log_meeting(manager(), client, held_at=timezone.now(), kind="phone")
    assert not Task.objects.filter(client=client, kind="sales").exists()


# ---- figures


def test_win_rate_and_days_to_win():
    today = timezone.localdate()
    won = prospect("W Ltd", stage_key="won")
    ProspectDetails.objects.filter(client=won).update(
        won_on=today, enquiry_date=today - timedelta(days=40)
    )
    lost = prospect("L Ltd", stage_key="lost")
    ProspectDetails.objects.filter(client=lost).update(lost_on=today)
    figures = services.header_figures([])
    assert figures["win_rate"] == 50 and figures["average_days"] == 40


def test_no_decisions_means_no_win_rate():
    assert services.header_figures([])["win_rate"] is None
