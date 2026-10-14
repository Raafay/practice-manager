from datetime import date

import pytest
from django.utils import timezone

from apps.clients.models import Client
from apps.clients.tests.factories import ClientContactFactory, ContactFactory
from apps.comms import schedules
from apps.comms.models import MessageTemplate, QueuedMessage, ReminderSchedule
from apps.comms.seed import SCHEDULES, TEMPLATES
from apps.tasks.tests.factories import make_task

from .factories import client_with_contact, make_deadline

pytestmark = pytest.mark.django_db


def schedule(key="vat_records", **changes) -> ReminderSchedule:
    row = ReminderSchedule.objects.get(key=key)
    for name, value in changes.items():
        setattr(row, name, value)
    row.active = changes.get("active", True)
    row.save()
    return row


def vat_deadline(client, **kwargs):
    kwargs.setdefault("due", date(2026, 11, 7))
    kwargs.setdefault("period_end", date(2026, 9, 30))
    return make_deadline(client, rule="vat_return", **kwargs)


def test_the_eight_schedules_are_seeded_inactive_with_held_templates():
    assert ReminderSchedule.objects.count() == len(SCHEDULES) == 8
    assert not ReminderSchedule.objects.filter(active=True).exists()
    assert MessageTemplate.objects.filter(key__in=[t["key"] for t in TEMPLATES]).count() == 8
    assert not MessageTemplate.objects.exclude(send_mode="hold").exists()
    for row in ReminderSchedule.objects.all():
        assert row.template.body and row.template.subject


def test_nothing_is_made_while_a_schedule_is_off():
    client, _ = client_with_contact()
    vat_deadline(client)
    assert schedules.run_all(date(2026, 10, 5)) == {"created": 0}


@pytest.mark.parametrize(
    ("key", "base", "expected"),
    [
        (
            "vat_records",
            date(2026, 9, 30),
            [date(2026, 10, 5), date(2026, 10, 10), date(2026, 10, 15), date(2026, 10, 20)],
        ),
        ("ct_payment", date(2026, 12, 1), [date(2026, 11, 1), date(2026, 11, 24)]),
        ("paye_payment", date(2026, 11, 22), [date(2026, 11, 17)]),
        ("sa_payment", date(2027, 1, 31), [date(2027, 1, 17)]),
        (
            "confirmation_statement",
            date(2027, 7, 14),
            [date(2027, 6, 16), date(2027, 6, 23), date(2027, 6, 30), date(2027, 7, 7)],
        ),
        ("sa_records", date(2027, 4, 5), [date(2027, 4, 20)] + [None] * 0),
    ],
)
def test_fire_dates_table(key, base, expected):
    row = ReminderSchedule.objects.get(key=key)
    dates = schedules.fire_dates(row, base)
    if key == "sa_records":
        assert dates[0] == date(2027, 4, 20)  # "20 April"
        assert len(dates) == 7
    else:
        assert dates == expected


def test_payroll_changes_count_working_days():
    row = ReminderSchedule.objects.get(key="payroll_changes")
    # Pay day Friday 30/10/2026: five working days before is Friday 23/10/2026.
    assert schedules.fire_dates(row, date(2026, 10, 30)) == [date(2026, 10, 23)]


def test_accounts_records_repeat_every_21_days():
    row = ReminderSchedule.objects.get(key="accounts_records")
    dates = schedules.fire_dates(row, date(2026, 12, 31))
    assert dates[0] == date(2027, 1, 7)
    assert [(b - a).days for a, b in zip(dates, dates[1:], strict=False)] == [21, 21, 21, 21]


def test_a_message_is_made_on_the_day_and_once():
    client, contact = client_with_contact()
    vat_deadline(client)
    schedule()
    assert schedules.run_all(date(2026, 10, 4))["created"] == 0
    assert schedules.run_all(date(2026, 10, 5))["created"] == 1
    assert schedules.run_all(date(2026, 10, 5))["created"] == 0
    message = QueuedMessage.objects.get()
    assert message.state == "needs_approval"
    assert message.to == "pat.sample@example.com"
    assert message.duplicate_key.startswith("schedule:")
    assert "30/09/2026" in message.subject
    assert "VAT" in message.reason
    assert message.created_by is None


def test_it_repeats_on_time():
    client, _ = client_with_contact()
    vat_deadline(client)
    schedule()
    for day in (date(2026, 10, 5), date(2026, 10, 10), date(2026, 10, 15), date(2026, 10, 20)):
        assert schedules.run_all(day)["created"] == 1
    assert schedules.run_all(date(2026, 10, 25))["created"] == 0
    assert QueuedMessage.objects.count() == 4
    keys = sorted(QueuedMessage.objects.values_list("duplicate_key", flat=True))
    assert [k.rsplit(":", 1)[1] for k in keys] == ["0", "1", "2", "3"]


def test_a_date_missed_for_over_three_days_is_not_sent_late():
    client, _ = client_with_contact()
    vat_deadline(client)
    schedule()
    assert schedules.run_all(date(2026, 10, 9))["created"] == 0
    assert schedules.run_all(date(2026, 10, 8))["created"] == 1  # 3 days late is still sent


def test_a_ticked_stop_step_stops_reminders():
    client, _ = client_with_contact()
    deadline = vat_deadline(client)
    task = make_task(None, title="VAT", client=client)
    task.deadline = deadline
    task.save()
    step = task.steps.create(name="Records received", stops_reminders=True)
    schedule()
    assert schedules.run_all(date(2026, 10, 5))["created"] == 1
    step.done_at = timezone.now()
    step.save()
    assert schedules.run_all(date(2026, 10, 10))["created"] == 0


def test_a_done_deadline_gets_no_reminders():
    client, _ = client_with_contact()
    deadline = vat_deadline(client)
    schedule()
    deadline.status = "done"
    deadline.save()
    assert schedules.run_all(date(2026, 10, 5))["created"] == 0


@pytest.mark.parametrize("status", [Client.Status.FORMER, Client.Status.LOST])
def test_former_and_lost_clients_are_skipped(status):
    client, _ = client_with_contact(status=status)
    vat_deadline(client)
    schedule()
    assert schedules.run_all(date(2026, 10, 5))["created"] == 0


def test_do_not_send_automatic_messages_is_respected():
    client, _ = client_with_contact(no_auto_messages=True)
    vat_deadline(client)
    schedule()
    assert schedules.run_all(date(2026, 10, 5))["created"] == 0


def test_recipients_are_the_main_contact_and_those_marked_for_reminders():
    client, _ = client_with_contact()
    other = ContactFactory(email="second@example.com")
    ClientContactFactory(client=client, contact=other, receives_reminders=True)
    silent = ContactFactory(email="silent@example.com")
    ClientContactFactory(client=client, contact=silent, receives_reminders=False)
    vat_deadline(client)
    schedule()
    schedules.run_all(date(2026, 10, 5))
    message = QueuedMessage.objects.get()
    assert set(message.to_list) == {"pat.sample@example.com", "second@example.com"}


def test_a_client_with_no_address_still_gets_a_flagged_draft():
    client, _ = client_with_contact(email="")
    vat_deadline(client)
    schedule()
    schedules.run_all(date(2026, 10, 5))
    message = QueuedMessage.objects.get()
    assert message.to == ""
    from apps.comms import services

    assert "No email address." in services.approval_problems(message)


def test_automatic_templates_are_approved_without_a_person_but_held_ones_are_not():
    client, _ = client_with_contact()
    vat_deadline(client)
    row = schedule()
    row.template.send_mode = "auto"
    row.template.body = "<p>Dear {{ contact.first_name }}, records please.</p>"
    row.template.save()
    schedules.run_all(date(2026, 10, 5))
    message = QueuedMessage.objects.get()
    assert message.state == "approved"
    assert message.approved_by is None
    assert "automatically" in message.reason


def test_an_automatic_template_with_a_blocking_problem_still_waits_for_a_person():
    client, _ = client_with_contact()
    vat_deadline(client)
    row = schedule()
    row.template.send_mode = "auto"
    row.template.body += "<p>{{ proposal_link }}</p>"  # no page to point to: blocks sending
    row.template.save()
    schedules.run_all(date(2026, 10, 5))
    assert QueuedMessage.objects.get().state == "needs_approval"


def test_task_based_schedule_before_target_date():
    from apps.tasks.models import TaskTemplate

    client, _ = client_with_contact()
    template = TaskTemplate.objects.first()
    task = make_task(None, title="Prepare accounts", client=client, target_date=date(2026, 11, 20))
    task.template = template
    task.save()
    row = ReminderSchedule.objects.get(key="payroll_changes")
    row.trigger = "before_target"
    row.offsets = [7]
    row.working_days = False
    row.active = True
    row.save()
    # With no task template set, nothing matches rather than everything.
    assert schedules.run_all(date(2026, 11, 13))["created"] == 0
    row.task_template = template
    row.save()
    assert schedules.run_all(date(2026, 11, 12))["created"] == 0
    assert schedules.run_all(date(2026, 11, 13))["created"] == 1
    assert schedules.run_all(date(2026, 11, 13))["created"] == 0


def test_step_ticked_trigger_fires_once():
    from apps.tasks.models import TaskTemplate

    client, _ = client_with_contact()
    task = make_task(None, title="Prepare accounts", client=client)
    template = TaskTemplate.objects.first()
    task.template = template
    task.save()
    step = task.steps.create(name="Draft sent", done_at=timezone.now())
    row = ReminderSchedule.objects.get(key="payroll_changes")
    row.trigger = "step_ticked"
    row.task_template = template
    row.step_name = step.name
    row.active = True
    row.save()
    assert schedules.run_all(date(2026, 10, 5))["created"] == 1
    assert schedules.run_all(date(2026, 10, 6))["created"] == 0


def test_demo_data_fills_the_queue_in_every_state_and_is_safe_to_run_twice():
    import io

    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    first = QueuedMessage.objects.count()
    call_command("seed_demo", stdout=io.StringIO())
    assert first == QueuedMessage.objects.count() >= 10
    states = set(QueuedMessage.objects.values_list("state", flat=True))
    assert {"needs_approval", "approved", "sent", "failed", "cancelled"} <= states
    assert QueuedMessage.objects.filter(to="").exists()
    assert ReminderSchedule.objects.filter(active=True).count() == 2
