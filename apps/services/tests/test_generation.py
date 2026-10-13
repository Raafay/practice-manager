from datetime import date

import pytest

from apps import events  # noqa: F401
from apps.accounts.tests.factories import owner
from apps.clients import services as client_services
from apps.clients.models import Client
from apps.companieshouse.services import client_synced
from apps.events.models import ActivityEvent
from apps.services import deadlines, services
from apps.services.models import ClientService, Deadline

from .factories import company, service, take

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 12)


def keys(client, rule):
    return sorted(client.deadlines.filter(rule=rule).values_list("period_key", flat=True))


def test_running_the_job_twice_creates_nothing_the_second_time():
    client = company(
        next_accounts_made_up_to=date(2026, 12, 31),
        next_accounts_due=date(2027, 9, 30),
        vat_frequency="monthly",
        payroll_frequency="monthly",
        pay_day_rule="last_working_day",
    )
    for code in ("accounts", "vat", "payroll"):
        take(client, code)
    first = deadlines.generate_for_client(client, today=TODAY)
    assert first.created
    count = Deadline.objects.count()
    second = deadlines.generate_for_client(client, today=TODAY)
    assert not second
    assert Deadline.objects.count() == count
    assert deadlines.generate_all(today=TODAY)["created"] == 0


def test_a_client_without_accounts_gets_no_ch_accounts_deadline():
    client = company(
        next_accounts_made_up_to=date(2026, 12, 31), next_accounts_due=date(2027, 9, 30)
    )
    take(client, "confirmation")
    deadlines.generate_for_client(client, today=TODAY)
    assert not client.deadlines.filter(rule="ch_accounts").exists()


def test_a_service_starting_on_1_october_gets_the_quarter_ended_30_september():
    # CORRECTIONS 9: a period whose due date is on or after the start date is created.
    client = company(vat_frequency="quarterly", vat_stagger=1)
    take(client, "vat", starts_on=date(2026, 10, 1))
    deadlines.generate_for_client(client, today=TODAY)
    assert "2026-09-30" in keys(client, "vat_return")
    assert "2026-06-30" not in keys(client, "vat_return")
    deadline = client.deadlines.get(rule="vat_return", period_key="2026-09-30")
    assert deadline.due_date == date(2026, 11, 7)
    assert deadline.original_due_date == date(2026, 11, 7)
    assert deadline.source == "calculated"
    assert deadline.source_note.startswith("Calculated")


def test_a_service_that_started_long_ago_is_not_given_years_of_history():
    client = company(vat_frequency="monthly")
    take(client, "vat", starts_on=date(2022, 1, 1))
    deadlines.generate_for_client(client, today=TODAY)
    assert min(client.deadlines.values_list("due_date", flat=True)) >= date(2026, 8, 13)


def test_switching_a_service_off_marks_later_open_deadlines_not_required():
    boss = owner()
    client = company(vat_frequency="monthly")
    cs = take(client, "vat", starts_on=date(2026, 9, 1))
    deadlines.generate_for_client(client, today=date(2026, 11, 20))
    services.end_service(boss, cs, date(2026, 9, 30))
    state = {d.period_key: d.status for d in client.deadlines.all()}
    assert state["2026-09-30"] == "open"
    assert state["2026-10-31"] == "not_required"
    assert state["2026-11-30"] == "not_required"
    assert ActivityEvent.objects.filter(verb="service.ended", client=client).exists()
    # and the job no longer creates anything for the ended service
    assert not deadlines.generate_for_client(client, today=date(2026, 12, 20))


@pytest.mark.parametrize("status", ["paused", "former", "onboarding", "prospect"])
def test_a_client_who_is_not_live_gets_nothing_new(status):
    client = company(status=status, vat_frequency="monthly")
    take(client, "vat")
    assert not deadlines.generate_for_client(client, today=TODAY)
    assert client.deadlines.count() == 0


def test_a_client_who_is_paused_keeps_the_open_ones():
    client = company(vat_frequency="monthly")
    take(client, "vat", starts_on=date(2026, 9, 1))
    deadlines.generate_for_client(client, today=TODAY)
    count = client.deadlines.count()
    client.status = Client.Status.PAUSED
    client.save()
    deadlines.generate_for_client(client, today=date(2027, 3, 1))
    assert client.deadlines.count() == count
    assert client.deadlines.filter(status="open").count() == count


def test_an_archived_client_gets_nothing():
    from django.utils import timezone

    client = company(vat_frequency="monthly", archived_at=timezone.now())
    take(client, "vat")
    assert not deadlines.generate_for_client(client, today=TODAY)


# ---------------------------------------------------------------- Companies House


def accounts_client(**kwargs):
    client = company(
        last_accounts_made_up_to=date(2025, 3, 31),
        next_accounts_made_up_to=date(2026, 3, 31),
        next_accounts_due=date(2026, 12, 31),
        **kwargs,
    )
    take(client, "accounts")
    return client


def test_ch_accounts_deadline_is_created_with_the_companies_house_source():
    client = accounts_client()
    deadlines.generate_for_client(client, today=TODAY)
    deadline = client.deadlines.get(rule="ch_accounts")
    assert (deadline.period_end, deadline.due_date) == (date(2026, 3, 31), date(2026, 12, 31))
    assert deadline.source == "companies_house"
    assert deadline.source_note == "From Companies House"
    assert deadline.label == "Year end 31/03/2026"


def test_a_changed_due_date_updates_the_open_deadline_in_place():
    client = accounts_client()
    deadlines.generate_for_client(client, today=TODAY)
    original = client.deadlines.get(rule="ch_accounts")
    client.next_accounts_due = date(2027, 1, 31)
    client.save()
    result = deadlines.generate_for_client(client, today=TODAY)
    assert len(result.updated) == 1
    assert client.deadlines.filter(rule="ch_accounts").count() == 1
    original.refresh_from_db()
    assert original.due_date == date(2027, 1, 31)
    assert ActivityEvent.objects.filter(verb="deadline.updated", client=client).exists()


def test_a_moved_year_end_updates_the_open_deadline_in_place():
    client = accounts_client()
    deadlines.generate_for_client(client, today=TODAY)
    original = client.deadlines.get(rule="ch_accounts")
    client.next_accounts_made_up_to = date(2026, 6, 30)
    client.next_accounts_due = date(2027, 3, 31)
    client.save()
    deadlines.generate_for_client(client, today=TODAY)
    assert client.deadlines.filter(rule="ch_accounts").count() == 1
    original.refresh_from_db()
    assert (original.period_end, original.period_key, original.due_date) == (
        date(2026, 6, 30),
        "2026-06-30",
        date(2027, 3, 31),
    )
    assert original.status == "open"


def test_a_filing_marks_the_deadline_done_and_creates_the_next():
    client = accounts_client()
    deadlines.generate_for_client(client, today=TODAY)
    first = client.deadlines.get(rule="ch_accounts")
    client.last_accounts_made_up_to = date(2026, 3, 31)
    client.next_accounts_made_up_to = date(2027, 3, 31)
    client.next_accounts_due = date(2027, 12, 31)
    client.save()
    result = deadlines.generate_for_client(client, today=TODAY)
    first.refresh_from_db()
    assert first.status == "done"
    assert first.evidence == "Shown as filed at Companies House, seen 12/10/2026"
    assert len(result.done) == 1
    assert keys(client, "ch_accounts") == ["2026-03-31", "2027-03-31"]
    assert client.deadlines.get(rule="ch_accounts", period_key="2027-03-31").status == "open"


def test_a_confirmation_statement_filing_is_detected_too():
    client = company(
        last_statement_made_up_to=date(2025, 10, 19),
        next_statement_made_up_to=date(2026, 10, 19),
        next_statement_due=date(2026, 11, 2),
    )
    take(client, "confirmation")
    deadlines.generate_for_client(client, today=TODAY)
    client.last_statement_made_up_to = date(2026, 10, 19)
    client.next_statement_made_up_to = date(2027, 10, 19)
    client.next_statement_due = date(2027, 11, 2)
    client.save()
    deadlines.generate_for_client(client, today=date(2026, 10, 20))
    states = dict(client.deadlines.values_list("period_key", "status"))
    assert states == {"2026-10-19": "done", "2027-10-19": "open"}


def test_the_end_of_a_companies_house_sync_creates_deadlines():
    client = accounts_client()
    client_synced.send(sender=Client, client=client, result=None)
    assert client.deadlines.filter(rule="ch_accounts").count() == 1


def test_ct600_follows_the_accounts_period_and_is_done_by_staff_only():
    client = accounts_client()
    take(client, "ct600")
    deadlines.generate_for_client(client, today=TODAY)
    assert keys(client, "ct600") == ["2026-03-31"]
    assert client.deadlines.get(rule="ct600").due_date == date(2027, 3, 31)
    client.last_accounts_made_up_to = date(2026, 3, 31)
    client.next_accounts_made_up_to = date(2027, 3, 31)
    client.next_accounts_due = date(2027, 12, 31)
    client.save()
    deadlines.generate_for_client(client, today=TODAY)
    assert client.deadlines.get(rule="ct600", period_key="2026-03-31").status == "open"


# ---------------------------------------------------------------- actions


def make_deadline():
    client = company(vat_frequency="monthly")
    take(client, "vat", starts_on=date(2026, 9, 1))
    deadlines.generate_for_client(client, today=TODAY)
    return client, client.deadlines.get(period_key="2026-09-30")


def test_mark_done_and_reopen():
    boss = owner()
    client, deadline = make_deadline()
    deadlines.mark_done(boss, deadline, done_on=date(2026, 10, 5), note="Filed online")
    deadline.refresh_from_db()
    assert (deadline.status, deadline.done_on, deadline.done_by) == (
        "done",
        date(2026, 10, 5),
        boss,
    )
    deadlines.reopen(boss, deadline)
    deadline.refresh_from_db()
    assert (deadline.status, deadline.done_on, deadline.done_note) == ("open", None, "")
    assert ActivityEvent.objects.filter(client=client, verb="deadline.done").exists()
    assert ActivityEvent.objects.filter(client=client, verb="deadline.reopened").exists()


def test_not_required_needs_a_reason():
    from django.core.exceptions import ValidationError

    boss = owner()
    _client, deadline = make_deadline()
    with pytest.raises(ValidationError):
        deadlines.mark_not_required(boss, deadline, reason="  ")
    deadlines.mark_not_required(boss, deadline, reason="Dormant this period")
    deadline.refresh_from_db()
    assert deadline.status == "not_required"
    assert deadline.override_reason == "Dormant this period"


def test_changing_the_date_keeps_the_original_and_needs_a_reason():
    from django.core.exceptions import ValidationError

    boss = owner()
    client, deadline = make_deadline()
    with pytest.raises(ValidationError):
        deadlines.change_due_date(boss, deadline, date(2026, 11, 14), reason="")
    deadlines.change_due_date(boss, deadline, date(2026, 11, 14), reason="HMRC extension")
    deadline.refresh_from_db()
    assert deadline.due_date == date(2026, 11, 14)
    assert deadline.original_due_date == date(2026, 11, 7)
    assert deadline.source == "manual"
    assert deadline.changed_by_hand
    assert "HMRC extension" in deadline.source_note
    # the job leaves a date changed by hand alone
    deadlines.generate_for_client(client, today=TODAY)
    deadline.refresh_from_db()
    assert deadline.due_date == date(2026, 11, 14)


def test_a_companies_house_date_cannot_be_changed_by_hand():
    from django.core.exceptions import ValidationError

    boss = owner()
    client = accounts_client()
    deadlines.generate_for_client(client, today=TODAY)
    deadline = client.deadlines.get(rule="ch_accounts")
    with pytest.raises(ValidationError):
        deadlines.change_due_date(boss, deadline, date(2027, 1, 31), reason="Late")


def test_a_deadline_that_is_not_open_cannot_be_marked_done_again():
    from django.core.exceptions import ValidationError

    boss = owner()
    _client, deadline = make_deadline()
    deadlines.mark_done(boss, deadline)
    with pytest.raises(ValidationError):
        deadlines.mark_done(boss, deadline)


def test_shown_state_is_worked_out_not_stored():
    _client, deadline = make_deadline()  # due 07/11/2026
    assert deadline.shown_state(date(2026, 10, 12)) == "upcoming"
    assert deadline.shown_state(date(2026, 10, 24)) == "due_soon"
    assert deadline.shown_state(date(2026, 11, 7)) == "due_soon"
    assert deadline.shown_state(date(2026, 11, 8)) == "overdue"
    deadline.status = "done"
    assert deadline.shown_state(date(2026, 11, 8)) == "done"


def test_the_uniqueness_is_on_client_rule_and_period_key():
    from django.db import IntegrityError, transaction

    client, deadline = make_deadline()
    with pytest.raises(IntegrityError), transaction.atomic():
        Deadline.objects.create(
            client=client,
            rule=deadline.rule,
            period_key=deadline.period_key,
            label="x",
            due_date=date(2026, 12, 1),
            original_due_date=date(2026, 12, 1),
        )


# ---------------------------------------------------------------- going live


def test_proposed_services_become_active_when_the_client_is_made_live():
    boss = owner()
    client = company(status="onboarding", vat_frequency="monthly")
    cs = services.switch_on(boss, client, service("vat"))
    assert cs.state == ClientService.State.PROPOSED
    assert cs.starts_on is None
    assert client.deadlines.count() == 0
    client_services.change_status(boss, client, "active")
    cs.refresh_from_db()
    assert cs.state == ClientService.State.ACTIVE
    assert cs.starts_on is not None
    assert client.deadlines.exists()


def test_changing_a_vat_setting_on_the_client_creates_deadlines():
    boss = owner()
    client = company()
    take(client, "vat", starts_on=date(2026, 9, 1))
    assert client.deadlines.count() == 0
    services.update_client_fields(boss, client, {"vat_frequency": "monthly"}, section="VAT")
    assert client.deadlines.exists()
