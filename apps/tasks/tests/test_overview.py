from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.events.models import Notification
from apps.tasks import services
from apps.tasks.models import Task

from .factories import accounts_client, make_task

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def test_the_overview_is_the_home_page_with_my_work_in_it(client):
    me = staff(name="Bob Staff")
    sign_in(client, me)
    make_task(me, title="Due today", owner=me, target_date=TODAY)
    make_task(me, title="Unowned")
    response = client.get(reverse("overview"))
    html = response.content.decode()
    assert response.status_code == 200 and reverse("overview") == "/"
    assert "Overview" in html and "Due today" in html and "1</strong> unassigned task" in html
    for heading in ("Deadlines in the next 14 days", "Waiting on me", "Overdue", "Today",
                    "Waiting on client"):  # fmt: skip
        assert heading in html


def test_deadlines_in_the_next_14_days_are_for_my_clients_only(client):
    me = staff(name="Bob Staff")
    sign_in(client, me)
    mine = accounts_client(manager=me, name="Mine Ltd")
    theirs = accounts_client(name="Theirs Ltd")
    for row, days in ((mine, 5), (theirs, 5)):
        deadline = row.deadlines.first()
        type(deadline).objects.filter(pk=deadline.pk).update(due_date=TODAY + timedelta(days=days))
    html = client.get(reverse("overview")).content.decode()
    assert "Mine Ltd" in html and "Theirs Ltd" not in html
    far = mine.deadlines.first()
    type(far).objects.filter(pk=far.pk).update(due_date=TODAY + timedelta(days=40))
    assert "Mine Ltd:" not in client.get(reverse("overview")).content.decode()


def test_waiting_on_me_lists_reviews_and_mentions(client):
    me, other = staff(name="Bob Staff"), owner(name="Ann Owner")
    sign_in(client, me)
    task = make_task(other, title="Please review", owner=other)
    services.set_field(other, task, "reviewer", me)
    services.add_comment(other, task, "Thoughts, @Bob?")
    html = client.get(reverse("overview")).content.decode()
    assert "Review: Please review" in html
    assert "mentioned you on Please review" in html
    Notification.objects.filter(user=me, kind="mention").update(read_at=timezone.now())
    assert "mentioned you" not in client.get(reverse("overview")).content.decode()


def test_the_old_home_page_name_still_works():
    from apps.tasks.views import MyWorkView, OverviewView

    assert MyWorkView is OverviewView


def test_shortcut_help_and_script_are_on_every_page(client):
    sign_in(client, staff())
    html = client.get(reverse("overview")).content.decode()
    assert 'id="shortcuts"' in html and "js/keys.js" in html
    assert 'data-go="t"' in html and 'data-go="c"' in html
    assert Task.objects.count() == 0
