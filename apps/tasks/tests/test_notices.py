from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.events.models import Notification
from apps.jobs.registry import get as get_job
from apps.tasks import notices, services
from apps.tasks.models import Task, TaskStep

from .factories import accounts_client, make_task, status

pytestmark = pytest.mark.django_db

MONDAY = date(2026, 10, 12)


def told(user, kind=None):
    rows = Notification.objects.filter(user=user)
    return rows.filter(kind=kind) if kind else rows


# ------------------------------------------------------------------ triggers


def test_assigning_a_task_tells_the_new_owner_but_not_yourself():
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    task = make_task(ann, title="Hand over")
    services.set_field(ann, task, "owner", bob)
    notice = told(bob, "assigned").get()
    assert "assigned you Hand over" in notice.message and notice.link == f"/tasks/{task.pk}/"
    services.set_field(ann, task, "owner", ann)
    assert told(ann).count() == 0


def test_creating_a_task_for_someone_else_tells_them_and_for_yourself_does_not():
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    make_task(ann, title="For Bob", owner=bob)
    make_task(ann, title="For me", owner=ann)
    assert told(bob, "assigned").count() == 1 and told(ann).count() == 0


def test_the_system_assigning_a_task_does_not_flood_the_owner():
    bob = staff()
    make_task(None, title="Generated", owner=bob)
    assert told(bob).count() == 0


def test_a_bulk_owner_change_tells_the_new_owner_for_each_task():
    ann, bob = owner(), staff()
    tasks = [make_task(ann, title=f"T{n}") for n in range(3)]
    services.bulk(ann, tasks, "owner", bob)
    assert told(bob, "assigned").count() == 3


def test_a_mention_tells_the_person_and_adds_them_as_a_follower():
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    task = make_task(ann, title="Discuss", owner=ann)
    services.add_comment(ann, task, "Can you look at this, @Bob?")
    assert told(bob, "mention").count() == 1 and bob in task.followers.all()
    assert told(bob, "comment").count() == 0  # one notice, not two
    services.add_comment(ann, task, "Note to self @Ann Owner")
    assert told(ann).count() == 0


def test_a_comment_tells_followers_but_not_the_author():
    ann, bob, cat = owner(name="Ann Owner"), staff(name="Bob Staff"), staff(name="Cat Staff")
    task = make_task(ann, title="Chat", owner=bob)
    task.followers.add(cat)
    services.add_comment(ann, task, "Update from me")
    assert told(bob, "comment").count() == 1 and told(cat, "comment").count() == 1
    assert told(ann).count() == 0
    services.add_comment(bob, task, "Reply")
    assert told(ann, "comment").count() == 1  # ann became a follower by commenting


def test_a_step_ticked_by_someone_else_tells_the_owner_only():
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    task = make_task(ann, title="Steps", owner=bob)
    TaskStep.objects.create(task=task, name="Gather", position=1)
    TaskStep.objects.create(task=task, name="Draft", position=2)
    first, second = task.steps.all()
    services.toggle_step(ann, first, done=True)
    assert told(bob, "step").count() == 1 and "Gather" in told(bob, "step").get().message
    services.toggle_step(bob, second, done=True)
    assert told(bob, "step").count() == 1  # not for your own tick
    services.toggle_step(ann, first, done=False)
    assert told(bob, "step").count() == 1  # unticking says nothing


def test_deadline_within_seven_days_and_still_to_do_tells_the_owner_once():
    bob = staff(name="Bob Staff")
    client_row = accounts_client()
    deadline = client_row.deadlines.first()
    type(deadline).objects.filter(pk=deadline.pk).update(due_date=MONDAY + timedelta(days=5))
    task = make_task(None, title="Close to deadline", client=client_row, owner=bob)
    Task.objects.filter(pk=task.pk).update(deadline=deadline)
    assert notices.deadline_notices(MONDAY) == {"notified": 1}
    notice = told(bob, "deadline").get()
    assert "17/10/2026" in notice.message and "To do" in notice.message
    assert notices.deadline_notices(MONDAY) == {"notified": 0}  # once only
    assert notices.deadline_notices(MONDAY + timedelta(days=1)) == {"notified": 0}
    assert told(bob).count() == 1


def test_no_deadline_notice_when_the_task_has_moved_on_or_the_deadline_is_far():
    bob = staff()
    client_row = accounts_client()
    deadline = client_row.deadlines.first()
    task = make_task(None, title="Far", client=client_row, owner=bob)
    Task.objects.filter(pk=task.pk).update(deadline=deadline)
    assert notices.deadline_notices(MONDAY) == {"notified": 0}  # due in 2027
    type(deadline).objects.filter(pk=deadline.pk).update(due_date=MONDAY + timedelta(days=2))
    services.set_field(bob, task, "status", status("In progress"))
    assert notices.deadline_notices(MONDAY) == {"notified": 0}
    Task.objects.filter(pk=task.pk).update(status=status("To do"), owner=None)
    assert notices.deadline_notices(MONDAY) == {"notified": 0}  # nobody to tell


def test_the_deadline_job_is_registered_before_the_email():
    assert get_job("task_notices").schedule.at.hour == 7
    assert get_job("daily_task_email").schedule.at.hour == 8


def test_the_bell_page_lists_notices_and_opening_one_marks_it_read(client):
    ann, bob = owner(name="Ann Owner"), staff(name="Bob Staff")
    task = make_task(ann, title="Look at me", owner=bob)
    sign_in(client, bob)
    assert "assigned you Look at me" in client.get(reverse("events:notifications")).content.decode()
    notice = told(bob).get()
    response = client.post(reverse("events:notification_open", args=[notice.pk]))
    assert response["Location"] == f"/tasks/{task.pk}/"
    notice.refresh_from_db()
    assert notice.read_at is not None


# ------------------------------------------------------------------ daily email


def build_day(user):
    make_task(user, title="Was due", owner=user, target_date=MONDAY - timedelta(days=2))
    make_task(user, title="Due now", owner=user, target_date=MONDAY)
    make_task(user, title="Due Friday", owner=user, target_date=MONDAY + timedelta(days=4))
    make_task(user, title="Due later", owner=user, target_date=MONDAY + timedelta(days=12))
    make_task(user, title="Someone else's", target_date=MONDAY)


def test_the_daily_email_lists_overdue_today_and_this_week(mailoutbox):
    bob = staff(name="Bob Staff", email="bob@example.com")
    build_day(bob)
    assert notices.send_daily_emails(MONDAY) == {"sent": 1}
    (email,) = mailoutbox
    assert email.to == ["bob@example.com"]
    body = email.body
    assert body.index("Overdue (1)") < body.index("Due today (1)") < body.index("Due this week (1)")
    assert "Was due" in body and "Due now" in body and "Due Friday" in body
    assert "Due later" not in body and "Someone else's" not in body
    assert "/tasks/" in body and "Bob" in body
    assert "1 overdue, 1 due today" in email.subject


def test_each_part_of_the_email_can_be_switched_off(mailoutbox):
    bob = staff(name="Bob Staff", email="bob@example.com", email_overdue=False)
    build_day(bob)
    notices.send_daily_emails(MONDAY)
    body = mailoutbox[0].body
    assert "Was due" not in body and "Due now" in body and "Due Friday" in body
    mailoutbox.clear()
    bob.email_today = bob.email_week = False
    bob.save()
    assert notices.send_daily_emails(MONDAY) == {"sent": 0}
    assert mailoutbox == []


def test_no_email_for_nothing_to_report_or_on_a_non_working_day(mailoutbox):
    staff(name="Idle", email="idle@example.com")
    assert notices.send_daily_emails(MONDAY) == {"sent": 0}
    bob = staff(email="bob@example.com")
    build_day(bob)
    saturday = date(2026, 10, 17)
    assert notices.send_daily_emails(saturday)["sent"] == 0
    bank_holiday = date(2026, 12, 25)
    assert notices.send_daily_emails(bank_holiday)["sent"] == 0
    assert mailoutbox == []


def test_a_task_waiting_on_the_client_is_left_out_of_the_email(mailoutbox):
    bob = staff(email="bob@example.com")
    waiting = make_task(bob, title="Chasing", owner=bob, target_date=MONDAY)
    services.set_field(bob, waiting, "status", status("Waiting on client"))
    notices.send_daily_emails(MONDAY)
    assert mailoutbox == []


def test_the_switches_are_on_the_profile_page(client):
    bob = staff(name="Bob Staff")
    sign_in(client, bob)
    page = client.get(reverse("accounts:profile")).content.decode()
    for name in ("email_overdue", "email_today", "email_week"):
        assert f'name="{name}"' in page
    client.post(
        reverse("accounts:profile"),
        {"name": "Bob Staff", "initials": "BS", "colour": "#64748b", "job_title": "",
         "weekly_hours": "37.5", "email_signature": "", "email_today": "on"},
    )  # fmt: skip
    bob.refresh_from_db()
    assert (bob.email_overdue, bob.email_today, bob.email_week) == (False, True, False)
