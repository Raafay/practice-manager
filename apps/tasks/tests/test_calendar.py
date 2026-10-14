from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import owner, sign_in
from apps.clients.models import SavedView
from apps.events.models import ActivityEvent
from apps.services.models import Deadline
from apps.tasks import calview

from .factories import accounts_client, make_task

pytestmark = pytest.mark.django_db

DAY = date(2026, 10, 12)  # a Monday


@pytest.fixture
def me(client):
    user = owner(name="Ann Owner")
    sign_in(client, user)
    return user


def go(client, **params):
    query = "&".join(f"{k}={v}" for k, v in {"layout": "calendar", **params}.items())
    return client.get(reverse("tasks:list") + "?" + query)


def test_a_drag_changes_the_target_date_and_never_the_due_date(client, me):
    task = make_task(me, title="Plan it", target_date=DAY, due_date=DAY + timedelta(days=30))
    before = ActivityEvent.objects.filter(verb="task.target_date_changed").count()
    response = client.post(reverse("tasks:calendar_move"), {"task": task.pk, "date": "2026-10-20"})
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.target_date == date(2026, 10, 20)
    assert task.due_date == DAY + timedelta(days=30)
    assert ActivityEvent.objects.filter(verb="task.target_date_changed").count() == before + 1
    assert not ActivityEvent.objects.filter(verb="task.due_date_changed").exists()


def test_dropping_on_the_side_list_clears_the_target_date(client, me):
    task = make_task(me, title="Unplan it", target_date=DAY)
    client.post(reverse("tasks:calendar_move"), {"task": task.pk, "date": ""})
    task.refresh_from_db()
    assert task.target_date is None


def test_a_bad_date_is_refused_and_nothing_changes(client, me):
    task = make_task(me, title="Keep", target_date=DAY)
    response = client.post(reverse("tasks:calendar_move"), {"task": task.pk, "date": "soon"})
    assert response.status_code == 422
    task.refresh_from_db()
    assert task.target_date == DAY


def test_month_grid_starts_on_a_monday_and_holds_whole_weeks():
    first, last, month_first, month_last = calview.bounds("month", DAY)
    assert (month_first, month_last) == (date(2026, 10, 1), date(2026, 10, 31))
    assert first == date(2026, 9, 28) and first.weekday() == 0
    assert last == date(2026, 11, 1) and last.weekday() == 6
    assert (last - first).days + 1 == 35
    week = calview.bounds("week", date(2026, 10, 14))
    assert week[0] == date(2026, 10, 12) and week[1] == date(2026, 10, 18)


def test_tasks_sit_on_their_target_date_or_their_deadline_date(client, me):
    make_task(me, title="Target day", target_date=date(2026, 10, 14), due_date=date(2026, 10, 28))
    html = go(client, date="2026-10-12").content.decode()
    assert 'data-date="2026-10-14"' in html
    block = html.split('data-date="2026-10-14"')[1].split("</ul>")[0]
    assert "Target day" in block
    html = go(client, date="2026-10-12", on="due").content.decode()
    block = html.split('data-date="2026-10-28"')[1].split("</ul>")[0]
    assert "Target day" in block
    assert "data-locked" in html and "data-calendar-task" not in html  # not draggable


def test_deadline_markers_appear_and_cannot_be_dragged(client, me):
    owned = accounts_client()
    deadline = Deadline.objects.filter(client=owned).order_by("due_date").first()
    make_task(me, title="Loose task", target_date=deadline.due_date)
    html = go(client, date=deadline.due_date.isoformat()).content.decode()
    assert f"{owned.name}: {deadline.label}" in html
    # Only real tasks carry the drag marker, never deadline markers.
    assert html.count("data-calendar-task") == html.count('id="cal-task-')
    marker_line = [ln for ln in html.splitlines() if "(deadline)" in ln][0]
    assert "data-calendar-task" not in marker_line


def test_tasks_with_no_date_wait_in_the_side_list(client, me):
    make_task(me, title="Someday")
    html = go(client, date="2026-10-12").content.decode()
    side = html.split('aria-labelledby="side-title"')[1]
    assert "Someday" in side and "No target date" in side


def test_week_layout_and_navigation_links(client, me):
    html = go(client, cal="week", date="2026-10-14").content.decode()
    assert "12/10/2026 to 18/10/2026" in html
    assert "date=2026-10-07" in html and "date=2026-10-21" in html


def test_clicking_a_day_opens_new_task_with_that_date(client, me):
    html = go(client, date="2026-10-12").content.decode()
    assert "/tasks/new/?target_date=2026-10-20" in html
    form = client.get(reverse("tasks:new") + "?target_date=2026-10-20").content.decode()
    assert 'value="2026-10-20"' in form


def test_a_saved_view_remembers_the_layout(client, me):
    client.post(
        reverse("tasks:view_save"), {"name": "Board by owner", "query": "layout=board&by=owner"}
    )
    saved = SavedView.objects.get()
    assert "layout=board" in saved.filters["qs"]
    html = client.get(reverse("tasks:list") + f"?view={saved.pk}").content.decode()
    assert 'data-board="owner"' in html
    client.post(
        reverse("tasks:view_save"), {"name": "Cal", "query": "layout=calendar&cal=week&on=due"}
    )
    cal = SavedView.objects.get(name="Cal")
    html = client.get(reverse("tasks:list") + f"?view={cal.pk}").content.decode()
    assert "data-calendar" in html and "12/10" not in html.split("<h2")[0]


def test_calendar_uses_the_same_filters(client, me):
    make_task(me, title="Mine", owner=me, target_date=date(2026, 10, 14))
    make_task(me, title="Theirs", target_date=date(2026, 10, 14))
    html = go(client, date="2026-10-12", chip="mine").content.decode()
    assert "Mine" in html and "Theirs" not in html
