from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import owner, sign_in
from apps.clients.tests.factories import ClientFactory
from apps.jobs.registry import get as get_job
from apps.tasks import repeating
from apps.tasks.models import RepeatingTask, Task

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 10, 12)


def rule(**kwargs) -> RepeatingTask:
    kwargs.setdefault("title", "Weekly catch-up")
    kwargs.setdefault("frequency", "weekly")
    kwargs.setdefault("first_date", MONDAY - timedelta(days=14))
    kwargs.setdefault("days_until_due", 4)
    return RepeatingTask.objects.create(**kwargs)


def test_the_job_makes_the_current_period_once_only():
    row = rule(client=ClientFactory(), owner=owner())
    assert repeating.create_due(MONDAY) == {"created": 1}
    assert repeating.create_due(MONDAY) == {"created": 0}
    assert repeating.create_due(MONDAY + timedelta(days=3)) == {"created": 0}  # same week
    task = Task.objects.get(repeating_task=row)
    assert task.start_date == MONDAY and task.target_date == MONDAY + timedelta(days=4)
    assert task.due_date is None and task.source == Task.Source.REPEATING
    assert task.title == "Weekly catch-up" and task.period_label == "Week of 12/10/2026"
    assert task.kind == "advisory" and task.owner == row.owner and task.client == row.client


def test_each_new_period_makes_one_more_task():
    rule()
    repeating.create_due(MONDAY)
    assert repeating.create_due(MONDAY + timedelta(days=7)) == {"created": 1}
    assert Task.objects.filter(repeating_task__isnull=False).count() == 2


def test_a_missed_period_is_skipped_not_made_late():
    rule()
    repeating.create_due(MONDAY + timedelta(days=28))  # nothing ran for weeks
    assert list(Task.objects.values_list("start_date", flat=True)) == [MONDAY + timedelta(days=28)]


def test_it_stops_after_the_end_date():
    row = rule(first_date=date(2026, 9, 7), ends_on=date(2026, 9, 20))
    assert repeating.create_due(date(2026, 9, 14)) == {"created": 1}
    assert repeating.create_due(date(2026, 9, 21)) == {"created": 0}
    assert repeating.create_due(date(2026, 12, 1)) == {"created": 0}
    assert Task.objects.filter(repeating_task=row).count() == 1


def test_it_waits_for_the_first_date_and_ignores_switched_off_rules():
    rule(first_date=MONDAY + timedelta(days=3))
    rule(title="Off", active=False)
    assert repeating.create_due(MONDAY) == {"created": 0}
    assert repeating.create_due(MONDAY + timedelta(days=3)) == {"created": 1}


@pytest.mark.parametrize(
    ("frequency", "first", "today", "expected_start"),
    [
        ("fortnightly", date(2026, 9, 28), date(2026, 10, 12), date(2026, 10, 12)),
        ("fortnightly", date(2026, 9, 28), date(2026, 10, 25), date(2026, 10, 12)),
        ("monthly", date(2026, 1, 31), date(2026, 3, 31), date(2026, 3, 31)),
        ("monthly", date(2026, 1, 31), date(2026, 3, 30), date(2026, 2, 28)),
        ("quarterly", date(2026, 1, 15), date(2026, 10, 14), date(2026, 7, 15)),
        ("quarterly", date(2026, 1, 15), date(2026, 10, 15), date(2026, 10, 15)),
        ("annual", date(2025, 11, 1), date(2026, 10, 31), date(2025, 11, 1)),
        ("annual", date(2025, 11, 1), date(2026, 11, 1), date(2026, 11, 1)),
    ],
)
def test_period_starts_for_every_frequency(frequency, first, today, expected_start):
    row = rule(frequency=frequency, first_date=first)
    assert repeating.current_period(row, today) == expected_start


def test_the_registered_job_runs_the_same_code():
    rule()
    job = get_job("repeating_tasks")
    assert job.schedule.at.hour == 3
    assert job.func(None)["created"] == 1


def test_the_form_creates_a_rule_and_the_first_task(client):
    boss = owner(name="Ann Owner")
    sign_in(client, boss)
    client_row = ClientFactory(name="Acorn Ltd")
    first = date.today()
    response = client.post(
        reverse("tasks:repeating_new"),
        {"title": "Monthly board pack", "client_text": client_row.name, "category": "",
         "owner": boss.pk, "frequency": "monthly", "first_date": first.isoformat(),
         "days_until_due": 10, "ends_on": "", "active": "on"},
    )  # fmt: skip
    assert response.status_code == 302
    row = RepeatingTask.objects.get()
    assert row.client == client_row and row.created_by == boss
    assert Task.objects.filter(repeating_task=row).count() == 1
    page = client.get(reverse("tasks:repeating")).content.decode()
    assert "Monthly board pack" in page and "Monthly" in page
    client.post(reverse("tasks:repeating_toggle", args=[row.pk]))
    row.refresh_from_db()
    assert row.active is False
    bad = client.post(
        reverse("tasks:repeating_new"),
        {"title": "Bad", "frequency": "weekly", "first_date": "2026-10-12", "ends_on": "2026-10-01",
         "days_until_due": 3},
    )  # fmt: skip
    assert bad.status_code == 422


def test_the_client_tasks_tab_offers_a_repeating_task(client):
    boss = owner()
    sign_in(client, boss)
    client_row = ClientFactory()
    html = client.get(reverse("tasks:client_tasks", args=[client_row.pk])).content.decode()
    assert f"{reverse('tasks:repeating_new')}?client={client_row.pk}" in html
    form = client.get(f"{reverse('tasks:repeating_new')}?client={client_row.pk}").content.decode()
    assert client_row.name in form
