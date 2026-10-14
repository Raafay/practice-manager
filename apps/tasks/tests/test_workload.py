from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.http import QueryDict
from django.urls import reverse

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.tasks import filters, services, workload
from apps.tasks.models import Task

from .factories import make_task

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 14)  # a Wednesday; this week is 12 to 18 October


def d(n):
    return TODAY + timedelta(days=n)


def rows_by_label():
    return {row.label: row for row in workload.build(TODAY)}


def test_numbers_for_a_small_set_of_tasks():
    ann = owner(name="Ann Owner", weekly_hours=Decimal("10"))
    bob = staff(name="Bob Staff", weekly_hours=Decimal("37.5"))
    # Ann: overdue (outside the 14 days), today, Thursday, Friday, next Tuesday, in 3 weeks.
    make_task(ann, title="Late", owner=ann, target_date=d(-3), estimate_minutes=60)
    make_task(ann, title="Today", owner=ann, target_date=d(0), estimate_minutes=120)
    make_task(ann, title="Friday", owner=ann, target_date=d(2), estimate_minutes=180)
    make_task(ann, title="Next Tue", owner=ann, target_date=d(6), estimate_minutes=240)
    make_task(ann, title="Far off", owner=ann, target_date=d(21), estimate_minutes=600)
    make_task(ann, title="No estimate", owner=ann, target_date=d(1))
    done = make_task(ann, title="Done", owner=ann, target_date=d(1), estimate_minutes=999)
    services.complete(ann, done)
    cancelled = make_task(ann, title="Cancelled", owner=ann, target_date=d(1), estimate_minutes=999)
    services.cancel(ann, cancelled)
    make_task(ann, title="Nobody's", target_date=d(3), estimate_minutes=30)
    make_task(bob, title="Bob's", owner=bob, due_date=d(4), estimate_minutes=90)

    rows = rows_by_label()
    a = rows["Ann Owner"]
    assert (a.open, a.overdue, a.this_week, a.next_week) == (6, 1, 3, 1)
    # Today, Friday, next Tuesday and the one with no estimate fall in the next 14 days.
    assert a.estimate_minutes == 120 + 180 + 240 and a.without_estimate == 1
    assert a.capacity_hours == Decimal("20") and a.hours == Decimal("9.0")
    assert a.percent == 45 and a.tone == "green"
    b = rows["Bob Staff"]
    assert (b.open, b.overdue, b.this_week, b.next_week) == (1, 0, 1, 0)
    assert b.estimate_minutes == 90 and b.capacity_hours == Decimal("75")  # a deadline counts too
    nobody = rows["Unassigned"]
    assert (nobody.open, nobody.this_week) == (1, 1) and nobody.capacity_hours is None
    assert nobody.percent is None and nobody.tone == "neutral"


@pytest.mark.parametrize(
    ("minutes", "percent", "tone"),
    [(60 * 17, 85, "green"), (60 * 17 + 6, 85, "green"), (60 * 18, 90, "amber"),
     (60 * 20, 100, "amber"), (60 * 20 + 60, 105, "red")],
)  # fmt: skip
def test_the_bar_is_amber_over_85_and_red_over_100(minutes, percent, tone):
    ann = owner(name="Ann Owner", weekly_hours=Decimal("10"))  # 20 hours in two weeks
    make_task(ann, title="Big", owner=ann, target_date=d(1), estimate_minutes=minutes)
    row = rows_by_label()["Ann Owner"]
    assert row.percent == percent and row.tone == tone
    assert row.bar <= 100


def test_every_number_links_to_a_table_that_shows_the_same_tasks(client):
    ann = owner(name="Ann Owner")
    sign_in(client, ann)
    make_task(ann, title="Late", owner=ann, target_date=date.today() - timedelta(days=2))
    make_task(ann, title="Soon", owner=ann, target_date=date.today())
    today = date.today()
    row = next(r for r in workload.build(today) if r.label == "Ann Owner")
    page = client.get(reverse("tasks:workload")).content.decode()
    assert f"?owner={ann.pk}&chip=overdue" in page and "Overdue" in page
    for chip, expected in (("overdue", row.overdue), ("this_week", row.this_week),
                           ("next_week", row.next_week), ("", row.open)):  # fmt: skip
        query, _ = filters.parse(QueryDict(f"owner={ann.pk}" + (f"&chip={chip}" if chip else "")))
        found = filters.apply(query, ann, today=today).count()
        assert found == expected, chip
    html = client.get(reverse("tasks:list") + f"?owner={ann.pk}&chip=next_week")
    assert html.status_code == 200


def test_the_workload_page_lists_everyone(client):
    sign_in(client, staff(name="Casey Staff"))
    page = client.get(reverse("tasks:workload")).content.decode()
    assert "Casey Staff" in page and "Unassigned" in page
    assert Task.objects.count() == 0
