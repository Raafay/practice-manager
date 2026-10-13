from datetime import date

import pytest

from apps.accounts.tests.factories import UserFactory, manager, owner, staff
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.services import deadlines
from apps.services.models import Deadline
from apps.services.tests.factories import take
from apps.tasks import generation, services
from apps.tasks.models import Task, TaskStep, TaskTemplate

from .factories import TODAY, accounts_client, status

pytestmark = pytest.mark.django_db


def template(service_code, rule, contains=""):
    return TaskTemplate.objects.get(
        service__code=service_code, rule=rule, name_pattern__contains=contains
    )


def test_one_task_per_deadline_and_template_and_none_on_a_second_run():
    client = accounts_client()
    titles = sorted(client.tasks.values_list("title", flat=True))
    assert titles == [
        "Accounts Preparation Year End 31/12/2026",
        "Companies House Submission Year End 31/12/2026",
    ]
    deadlines.generate_for_client(client, today=TODAY)
    generation.catch_up(today=TODAY)
    assert client.tasks.count() == 2
    deadline = client.deadlines.get(rule="ch_accounts")
    assert generation.create_for_deadline(deadline) == []


def test_tasks_copy_the_template_steps_and_flags():
    client = accounts_client()
    task = client.tasks.get(title__startswith="Companies House")
    step = task.steps.get()
    assert (step.name, step.is_filing, step.stops_reminders) == (
        "Filed at Companies House",
        True,
        False,
    )
    prep = client.tasks.get(title__startswith="Accounts Preparation")
    assert list(prep.steps.values_list("name", flat=True))[:2] == [
        "Records requested",
        "Records received",
    ]
    assert prep.steps.get(name="Records received").stops_reminders is True
    assert prep.kind == "compliance" and prep.source == "generated"
    assert prep.category.name == "Accounts" and prep.service.code == "accounts"


@pytest.mark.parametrize(
    ("code", "rule", "contains", "period_end", "due", "expected"),
    [
        # 60 days before 30/09/2027 is a Sunday, so it moves back to the Friday.
        (
            "accounts",
            "ch_accounts",
            "Preparation",
            date(2027, 3, 31),
            date(2027, 9, 30),
            date(2027, 7, 30),
        ),
        (
            "accounts",
            "ch_accounts",
            "Submission",
            date(2027, 3, 31),
            date(2027, 9, 30),
            date(2027, 8, 31),
        ),
        (
            "confirmation",
            "confirmation_statement",
            "",
            date(2026, 10, 20),
            date(2026, 11, 3),
            date(2026, 10, 27),
        ),
        # 31 October before the due date; 31/10/2027 is a Sunday.
        (
            "self_assessment",
            "self_assessment",
            "",
            date(2027, 4, 5),
            date(2028, 1, 31),
            date(2027, 10, 29),
        ),
        # Due in October: the 31st of the year before.
        (
            "self_assessment",
            "self_assessment",
            "",
            date(2026, 4, 5),
            date(2027, 1, 31),
            date(2026, 10, 30),
        ),
        # 14 days before the corporation tax payment date (01/10/2027).
        ("ct600", "ct600", "", date(2026, 12, 31), date(2027, 12, 31), date(2027, 9, 17)),
        # On the due date, moved back off a Saturday.
        ("bookkeeping", "periodic", "", date(2026, 10, 31), date(2026, 10, 31), date(2026, 10, 30)),
        # Two working days before pay day.
        ("payroll", "payroll_run", "", date(2026, 10, 31), date(2026, 10, 30), date(2026, 10, 28)),
    ],
)
def test_target_date_rules(code, rule, contains, period_end, due, expected):
    deadline = Deadline(rule=rule, period_end=period_end, due_date=due)
    target = generation.target_date_for(template(code, rule, contains), deadline)
    assert target == expected
    assert target.weekday() < 5


def test_target_date_skips_a_bank_holiday():
    # Due on the Boxing Day bank holiday (Monday 28/12/2026): back past the weekend and
    # Christmas Day to Thursday the 24th.
    deadline = Deadline(rule="periodic", period_end=date(2026, 12, 28), due_date=date(2026, 12, 28))
    assert generation.target_date_for(template("bookkeeping", "periodic"), deadline) == date(
        2026, 12, 24
    )


def test_name_patterns():
    deadline = Deadline(
        rule="payroll_run",
        label="October 2026",
        period_end=date(2026, 10, 31),
        due_date=date(2026, 10, 30),
    )
    assert generation.task_name(template("payroll", "payroll_run"), deadline) == "PAYE October 2026"
    ae = Deadline(rule="auto_enrolment_redeclaration", due_date=date(2026, 11, 5), label="x")
    assert (
        generation.task_name(template("auto_enrolment", "auto_enrolment_redeclaration"), ae)
        == "Auto-Enrolment Re-declaration due 05/11/2026"
    )


def test_default_owner_is_manager_then_partner_then_an_owner():
    mgr, prt, boss = manager(), manager(), owner()
    tpl = template("accounts", "ch_accounts", "Preparation")
    both = ClientFactory(manager=mgr, partner=prt)
    assert generation.default_owner(tpl, both) == mgr
    only_partner = ClientFactory(partner=prt)
    assert generation.default_owner(tpl, only_partner) == prt
    nobody = ClientFactory()
    assert generation.default_owner(tpl, nobody) == boss
    gone = UserFactory(is_active=False)
    assert generation.default_owner(tpl, ClientFactory(manager=gone)) == boss
    tpl.default_owner = TaskTemplate.Owner.NOBODY
    assert generation.default_owner(tpl, both) is None
    tpl.default_owner, tpl.owner_user = TaskTemplate.Owner.USER, staff()
    assert generation.default_owner(tpl, both) == tpl.owner_user
    tpl.default_owner = TaskTemplate.Owner.PARTNER
    assert generation.default_owner(tpl, both) == prt


def test_generated_tasks_get_the_clients_manager():
    mgr = manager()
    client = accounts_client(manager=mgr)
    assert set(client.tasks.values_list("owner", flat=True)) == {mgr.pk}


def test_no_tasks_for_a_paused_client_or_a_done_deadline():
    client = accounts_client()
    deadline = client.deadlines.get(rule="ch_accounts")
    client.tasks.all().delete()
    deadline.status = Deadline.Status.DONE
    deadline.save()
    assert generation.create_for_deadline(deadline) == []


def test_catch_up_makes_missing_tasks():
    client = accounts_client()
    client.tasks.all().delete()
    counts = generation.catch_up(today=TODAY)
    assert counts["created"] == 2
    assert generation.catch_up(today=TODAY)["created"] == 0


def test_due_date_follows_a_companies_house_change_and_is_logged():
    client = accounts_client()
    client.next_accounts_due = date(2027, 10, 31)
    client.save()
    deadlines.generate_for_client(client, today=TODAY)
    assert set(client.tasks.values_list("due_date", flat=True)) == {date(2027, 10, 31)}
    assert ActivityEvent.objects.filter(verb="task.due_changed").count() == 2


def test_due_date_follows_a_date_changed_by_hand():
    client = ClientFactory(vat_frequency="monthly")
    take(client, "vat", starts_on=date(2026, 9, 1))
    deadlines.generate_for_client(client, today=TODAY)
    deadline = client.deadlines.order_by("due_date").first()
    task = deadline.tasks.get()
    new = deadline.due_date.replace(day=28)
    deadlines.change_due_date(owner(), deadline, new, reason="HMRC extension")
    task.refresh_from_db()
    assert task.due_date == new


def test_catch_up_repairs_a_drifted_due_date():
    client = accounts_client()
    client.tasks.update(due_date=date(2020, 1, 1))
    generation.catch_up(today=TODAY)
    assert set(client.tasks.values_list("due_date", flat=True)) == {date(2027, 9, 30)}


def test_ticking_the_filing_step_marks_the_deadline_done():
    client = accounts_client()
    task = client.tasks.get(title__startswith="Companies House")
    boss = owner(name="Sara Sample")
    services.toggle_step(boss, task.steps.get())
    deadline = client.deadlines.get(rule="ch_accounts")
    assert deadline.status == Deadline.Status.DONE
    assert deadline.evidence == "Marked filed by Sara Sample"
    assert deadline.done_by == boss


def test_a_step_that_is_not_the_filing_step_leaves_the_deadline_open():
    client = accounts_client()
    task = client.tasks.get(title__startswith="Accounts Preparation")
    services.toggle_step(owner(), task.steps.first())
    assert client.deadlines.get(rule="ch_accounts").is_open


def test_a_deadline_done_elsewhere_offers_to_complete_its_tasks():
    client = accounts_client()
    deadline = client.deadlines.get(rule="ch_accounts")
    task = client.tasks.first()
    assert not services.offer_to_complete(task)
    deadlines.mark_done(owner(), deadline)
    task = Task.objects.select_related("deadline", "status").get(pk=task.pk)
    assert services.offer_to_complete(task)
    services.complete(owner(), task)
    assert not services.offer_to_complete(
        Task.objects.select_related("deadline", "status").get(pk=task.pk)
    )


def test_a_client_made_live_gets_its_tasks():
    client = ClientFactory(
        status="onboarding",
        next_accounts_made_up_to=date(2026, 12, 31),
        next_accounts_due=date(2027, 9, 30),
    )
    take(client, "accounts", state="proposed")
    assert not client.tasks.exists()
    from apps.clients import services as client_services

    client_services.change_status(owner(), client, "active")
    assert client.tasks.count() == 2


def test_step_count_matches_template():
    client = accounts_client()
    assert TaskStep.objects.filter(task__client=client).count() == 6
    assert status("To do").is_default
