from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.tasks.models import Task, TaskStatus
from apps.timekeeping import services
from apps.timekeeping.models import TimeEntry, Timer

pytestmark = pytest.mark.django_db


def make_task(client=None, **fields):
    return Task.objects.create(
        title="Prepare accounts", client=client, status=TaskStatus.objects.first(), **fields
    )


@pytest.mark.parametrize(
    "text, minutes",
    [
        ("1:30", 90),
        ("1.5", 90),
        ("90m", 90),
        ("1h 30m", 90),
        ("2h", 120),
        ("0:45", 45),
        ("45m", 45),
        ("0.25", 15),
    ],
)
def test_parse_duration(text, minutes):
    assert services.parse_duration(text) == minutes


@pytest.mark.parametrize("text", ["", "abc", "0", "0:00", "25", "1:75", "-1"])
def test_parse_duration_refuses(text):
    with pytest.raises(ValidationError):
        services.parse_duration(text)


def test_format_minutes():
    assert services.format_minutes(90) == "1h 30m"
    assert services.format_minutes(120) == "2h"
    assert services.format_minutes(5) == "5m"
    assert services.clock_text(95) == "1:35"


def test_one_running_timer_per_user_and_second_stops_first():
    person = staff()
    first, second = ClientFactory(), ClientFactory()
    t0 = timezone.now() - timedelta(minutes=30)
    services.start_timer(person, client=first, now=t0)
    services.start_timer(person, client=second)
    assert Timer.objects.filter(user=person).count() == 1
    assert Timer.objects.get(user=person).client == second
    entry = TimeEntry.objects.get(user=person)
    assert entry.client == first
    assert entry.minutes in (30, 31)
    assert entry.started_at and entry.ended_at


def test_timers_are_per_user():
    a, b = staff(), staff()
    services.start_timer(a)
    services.start_timer(b)
    assert Timer.objects.count() == 2


def test_stop_timer_with_nothing_running_does_nothing():
    assert services.stop_timer(staff()) is None


def test_timer_under_a_minute_saves_a_minute():
    person = staff()
    now = timezone.now()
    services.start_timer(person, now=now)
    entry = services.stop_timer(person, now=now + timedelta(seconds=10))
    assert entry.minutes == 1


def test_task_timer_takes_the_tasks_client():
    person = staff()
    client = ClientFactory()
    task = make_task(client)
    timer = services.start_timer(person, task=task)
    assert timer.client == client


def test_task_of_another_client_is_refused():
    with pytest.raises(ValidationError):
        services.log_time(
            staff(), minutes=10, client=ClientFactory(), task=make_task(ClientFactory())
        )


def test_edit_own_entry_but_not_anyone_elses():
    mine, theirs = staff(), staff()
    entry = services.log_time(mine, minutes=30)
    with pytest.raises(PermissionDenied):
        services.update_entry(theirs, entry, minutes=40)
    with pytest.raises(PermissionDenied):
        services.delete_entry(theirs, entry)
    services.update_entry(mine, entry, minutes=40)
    entry.refresh_from_db()
    assert entry.minutes == 40


def test_manager_and_owner_edit_anyones():
    entry = services.log_time(staff(), minutes=30)
    services.update_entry(manager(), entry, minutes=45)
    services.delete_entry(owner(), entry)
    assert not TimeEntry.objects.exists()


def test_staff_cannot_log_for_someone_else():
    with pytest.raises(PermissionDenied):
        services.log_time(staff(), minutes=30, user=staff())
    services.log_time(manager(), minutes=30, user=staff())


def test_week_grid_totals_against_weekly_hours():
    person = staff()
    monday = date(2026, 10, 12)
    client = ClientFactory()
    services.log_time(person, minutes=120, on_date=monday, client=client)
    services.log_time(person, minutes=60, on_date=monday + timedelta(days=1), client=client)
    services.log_time(person, minutes=30, on_date=monday)
    grid = services.week_grid(person, monday)
    assert grid["daily"][0] == 150 and grid["daily"][1] == 60
    assert grid["weekly"] == 210
    assert len(grid["rows"]) == 2
    assert grid["capacity_minutes"] == int(person.weekly_hours * 60)


def test_set_cell_creates_edits_and_clears():
    person = staff()
    client = ClientFactory()
    day = date(2026, 10, 12)
    services.set_cell(person, person, client=client, task=None, on_date=day, minutes=60)
    services.set_cell(person, person, client=client, task=None, on_date=day, minutes=90)
    assert TimeEntry.objects.get().minutes == 90
    services.set_cell(person, person, client=client, task=None, on_date=day, minutes=None)
    assert not TimeEntry.objects.exists()


def test_set_cell_refuses_a_box_with_several_entries():
    person = staff()
    day = date(2026, 10, 12)
    services.log_time(person, minutes=10, on_date=day)
    services.log_time(person, minutes=20, on_date=day)
    with pytest.raises(ValidationError):
        services.set_cell(person, person, client=None, task=None, on_date=day, minutes=30)


def test_client_totals():
    client = ClientFactory()
    a, b = staff(name="Ann"), staff(name="Bea")
    services.log_time(a, minutes=60, client=client, on_date=date(2026, 9, 3))
    services.log_time(b, minutes=30, client=client, on_date=date(2026, 10, 3))
    totals = services.client_totals(client)
    assert totals["total"] == 90
    assert dict(totals["months"]) == {"2026-09": 60, "2026-10": 30}
    assert dict(totals["people"]) == {"Ann": 60, "Bea": 30}


# ---------------------------------------------------------------- views


def test_timesheet_needs_sign_in(client):
    assert "/login/" in client.get(reverse("timekeeping:sheet"))["Location"]


def test_timesheet_shows_my_week(client):
    person = staff()
    sign_in(client, person)
    services.log_time(person, minutes=90, client=ClientFactory(name="Alder Ltd"))
    response = client.get(reverse("timekeeping:sheet"))
    assert response.status_code == 200
    assert b"Alder Ltd" in response.content and b"1:30" in response.content


def test_staff_cannot_open_another_persons_timesheet(client):
    me, other = staff(), staff()
    services.log_time(other, minutes=15, note="x", client=ClientFactory(name="Hidden Co"))
    sign_in(client, me)
    response = client.get(reverse("timekeeping:sheet"), {"user": other.pk})
    assert b"Hidden Co" not in response.content


def test_manager_can_open_another_persons_timesheet(client):
    other = staff()
    services.log_time(other, minutes=15, client=ClientFactory(name="Visible Co"))
    sign_in(client, manager())
    response = client.get(reverse("timekeeping:sheet"), {"user": other.pk})
    assert b"Visible Co" in response.content


def test_cell_post_saves_and_staff_cannot_write_for_others(client):
    me, other = staff(), staff()
    sign_in(client, me)
    c = ClientFactory()
    url = reverse("timekeeping:cell")
    ok = client.post(url, {"client": c.pk, "date": "2026-10-12", "value": "1:30"})
    assert ok.status_code == 204
    assert TimeEntry.objects.get(user=me).minutes == 90
    denied = client.post(
        url, {"client": c.pk, "date": "2026-10-12", "value": "1", "user": other.pk}
    )
    assert denied.status_code == 403


def test_cell_refuses_a_future_day(client):
    sign_in(client, staff())
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert (
        client.post(reverse("timekeeping:cell"), {"date": tomorrow, "value": "1"}).status_code
        == 404
    )


def test_log_time_form_saves(client):
    me = staff()
    sign_in(client, me)
    c = ClientFactory()
    response = client.post(
        reverse("timekeeping:client_log", args=[c.pk]),
        {
            "date": timezone.localdate().isoformat(),
            "duration": "0:45",
            "billable": "on",
            "note": "Call",
        },
    )
    assert response.status_code == 302
    entry = TimeEntry.objects.get()
    assert (entry.client, entry.minutes, entry.user, entry.note) == (c, 45, me, "Call")


def test_log_time_form_rejects_bad_time(client):
    sign_in(client, staff())
    response = client.post(
        reverse("timekeeping:log"), {"date": timezone.localdate().isoformat(), "duration": "lots"}
    )
    assert response.status_code == 422


def test_edit_and_delete_someone_elses_entry_is_403(client):
    entry = services.log_time(staff(), minutes=30)
    sign_in(client, staff())
    assert client.get(reverse("timekeeping:edit", args=[entry.pk])).status_code == 403
    assert client.post(reverse("timekeeping:delete", args=[entry.pk])).status_code == 403


def test_timer_views_and_top_bar(client):
    me = staff()
    sign_in(client, me)
    c = ClientFactory(name="Timed Co")
    client.post(reverse("timekeeping:timer_start"), {"client": c.pk})
    page = client.get(reverse("timekeeping:sheet"))
    assert b"Timed Co" in page.content and b"Stop the timer" in page.content
    client.post(reverse("timekeeping:timer_stop"))
    assert not Timer.objects.exists() and TimeEntry.objects.filter(user=me, client=c).exists()


def test_timer_next_address_must_be_local(client):
    sign_in(client, staff())
    response = client.post(reverse("timekeeping:timer_start"), {"next": "https://evil.example/"})
    assert response["Location"] == reverse("timekeeping:sheet")


def test_client_time_tab_and_task_drawer(client):
    me = staff()
    sign_in(client, me)
    c = ClientFactory()
    task = make_task(c, estimate_minutes=60)
    services.log_time(me, minutes=90, client=c, task=task)
    tab = client.get(reverse("timekeeping:client_tab", args=[c.pk]))
    assert tab.status_code == 200 and b"1h 30m" in tab.content
    drawer = client.get(reverse("tasks:detail", args=[task.pk]), HTTP_HX_REQUEST="true")
    assert b"1h 30m of 1h estimated" in drawer.content and b"Over estimate" in drawer.content


def test_workload_shows_hours_logged_this_week(client):
    me = staff(name="Logger Lee")
    services.log_time(me, minutes=150)
    sign_in(client, me)
    response = client.get(reverse("tasks:workload"))
    assert b"Logged this week" in response.content and b"2.5 h" in response.content
