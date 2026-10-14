"""Made-up tasks for development. Everything here is invented.

Safe to run twice. The compliance tasks come from the deadlines already made; this
tidies them (finished work is done, some is part-way) and adds 25 fractional tasks.
"""

from datetime import date, timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client

from . import generation, projects, repeating, services
from .models import (
    Project,
    ProjectTemplate,
    RepeatingTask,
    Task,
    TaskCategory,
    TaskKind,
    TaskStatus,
    TaskStep,
)

ADVISORY = [
    ("Monthly cash flow forecast refresh", "Cash flow and funding", 5),
    ("Review supplier payment terms", "Supplier and contract queries", 12),
    ("Draft board pack for the quarter", "Reporting and budgets", -4),
    ("Walk the finance team through the new approvals process", "Training and coaching", 9),
    ("Year-end insurance renewal comparison", "Insurance", 21),
    ("Agree chart of accounts changes", "Finance systems", -9),
    ("Credit control routine: review aged debtors", "Operations", 3),
    ("Check payroll query from the client's HR lead", "HR and payroll queries", 2),
    ("Set up purchase order approvals", "Internal controls", 15),
    ("Prepare budget versus actual commentary", "Reporting and budgets", 6),
    ("Loan covenant check", "Cash flow and funding", -2),
    ("Book-keeper coaching session", "Training and coaching", 8),
    ("Review expenses policy", "Internal controls", 30),
    ("Compare two card-payment providers", "Supplier and contract queries", 18),
    ("Monthly management meeting prep", "Reporting and budgets", 1),
    ("Stock count procedure review", "Operations", 25),
    ("Cloud accounting migration plan", "Finance systems", 40),
    ("Directors' insurance cover review", "Insurance", -6),
    ("Cash runway scenarios for the next 12 months", "Cash flow and funding", 11),
    ("Onboarding checklist for a new finance assistant", "Training and coaching", 14),
    ("Quarterly KPI dashboard", "Reporting and budgets", 7),
    ("Contract query: equipment lease", "Supplier and contract queries", 4),
    ("Pension provider query", "HR and payroll queries", -1),
    ("Segregation of duties review", "Internal controls", 20),
    ("Tidy the shared drive folder structure", "Other", 35),
]

STEPS = ["Information gathered", "Analysis done", "Draft sent", "Discussed with client"]
COMMENTS = [
    "Spoke to the client this morning. They will send the figures on Thursday.",
    "Draft is ready for a second pair of eyes. Ready for review.",
    "Client asked for this to be done before their board meeting.",
]


def _people() -> dict[str, User]:
    return {u.email: u for u in User.objects.staff().filter(is_active=True)}


def _tidy_generated(today: date) -> int:
    """Work for finished deadlines is done; some open work is part-way through."""
    done = TaskStatus.done_status()
    progress = TaskStatus.objects.filter(name="In progress").first() or TaskStatus.default()
    waiting = TaskStatus.objects.filter(is_waiting=True).first() or progress
    count = 0
    for task in Task.objects.filter(
        source=Task.Source.GENERATED, status__is_done=False
    ).select_related("deadline"):
        if task.deadline and not task.deadline.is_open:
            task.status, task.completed_at = done, timezone.now()
            task.save(update_fields=["status", "completed_at", "updated_at"])
            task.steps.filter(done_at__isnull=True).update(done_at=timezone.now())
            count += 1
    open_tasks = list(
        Task.objects.filter(source=Task.Source.GENERATED, status__is_done=False).order_by("pk")
    )
    for index, task in enumerate(open_tasks):
        if index % 4 == 1 and task.status_id == TaskStatus.default().pk:
            task.status = progress
            task.save(update_fields=["status", "updated_at"])
            first = task.steps.first()
            if first and first.done_at is None and not first.is_filing:
                first.done_at = timezone.now()
                first.save(update_fields=["done_at", "updated_at"])
        elif index % 7 == 3:
            task.status = waiting
            task.save(update_fields=["status", "updated_at"])
    return count


REPEATING = [
    ("Weekly finance catch-up call", "weekly", 2, "Operations"),
    ("Monthly board pack", "monthly", 10, "Reporting and budgets"),
    ("Quarterly insurance and renewals check", "quarterly", 14, "Insurance"),
]


def _seed_projects(today: date) -> dict:
    """Two projects from templates at different points, and three repeating tasks."""
    if Project.objects.exists():
        return {"projects": Project.objects.count(), "repeating": RepeatingTask.objects.count()}
    people = list(_people().values())
    clients = list(
        Client.objects.filter(
            status=Client.Status.ACTIVE, client_services__service__kind="advisory"
        )
        .distinct()
        .order_by("name")
    ) or list(Client.objects.filter(status=Client.Status.ACTIVE).order_by("name")[:3])
    if not people or not clients:
        return {"projects": 0, "repeating": 0}
    done = TaskStatus.done_status()
    progress = TaskStatus.objects.filter(name="In progress").first() or TaskStatus.default()
    plans = [
        ("Finance function health check", 21, 6, 2),
        ("New starter finance training (12 weeks)", 5, 1, 1),
    ]
    for index, (template_name, started_days_ago, n_done, n_started) in enumerate(plans):
        template = ProjectTemplate.objects.filter(name=template_name).first()
        if template is None:
            continue
        owner = people[index % len(people)]
        project = projects.create_project(
            owner,
            name=f"{template_name.split(' (')[0]} for {clients[index % len(clients)].name}",
            client=clients[index % len(clients)],
            owner=owner,
            state=Project.State.ACTIVE,
            start_date=today - timedelta(days=started_days_ago),
            end_date=today + timedelta(days=75 if index else 50),
            budget_hours=40 if index == 0 else 60,
            description="Made-up demo project.",
            template=template,
        )
        tasks = list(project.tasks.order_by("position", "id"))
        for number, task in enumerate(tasks):
            helper = people[(index + number) % len(people)]
            if number < n_done and done:
                services.set_field(helper, task, "status", done)
            elif number < n_done + n_started:
                services.set_field(helper, task, "status", progress)
    for index, (title, frequency, days, category) in enumerate(REPEATING):
        client = clients[index % len(clients)] if index < 2 else None
        repeating.save(
            people[index % len(people)],
            RepeatingTask(
                client=client,
                title=title,
                category=TaskCategory.objects.filter(name=category).first(),
                owner=people[(index + 1) % len(people)],
                frequency=frequency,
                first_date=today - timedelta(days=60),
                days_until_due=days,
            ),
        )
    repeating.create_due(today)
    return {"projects": Project.objects.count(), "repeating": RepeatingTask.objects.count()}


def seed(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    generation.catch_up(today=today)
    finished = _tidy_generated(today)
    extras = _seed_projects(today)
    if Task.objects.filter(source=Task.Source.MANUAL, title=ADVISORY[0][0]).exists():
        return {
            "tasks": Task.objects.count(),
            "advisory_tasks": 0,
            "finished_tasks": finished,
            **extras,
        }

    people = _people()
    team = list(people.values())
    clients = list(
        Client.objects.filter(
            status=Client.Status.ACTIVE, client_services__service__kind="advisory"
        )
        .distinct()
        .order_by("name")
    ) or list(Client.objects.filter(status=Client.Status.ACTIVE).order_by("name")[:6])
    statuses = list(TaskStatus.objects.filter(is_done=False, active=True))
    made = 0
    for index, (title, category_name, offset) in enumerate(ADVISORY):
        author = team[index % len(team)] if team else None
        owner = None if index % 5 == 4 else team[(index + 1) % len(team)]
        target = today + timedelta(days=offset)
        task = services.create_task(
            author,
            title=title,
            client=clients[index % len(clients)] if clients else None,
            kind=TaskKind.ADVISORY,
            category=TaskCategory.objects.filter(name=category_name).first(),
            owner=owner,
            target_date=target,
            due_date=target + timedelta(days=7) if index % 3 == 0 else None,
            description=f"<div>{title}. Made-up demo task.</div>",
        )
        if index % 3 != 2:
            TaskStep.objects.bulk_create(
                TaskStep(task=task, name=name, position=(n + 1) * 10)
                for n, name in enumerate(STEPS)
            )
            for step in list(task.steps.all())[: index % 4]:
                services.toggle_step(owner or author, step, done=True)
        if index % 5 != 4:
            services.set_field(author, task, "status", statuses[index % len(statuses)])
        if index % 4 == 0 and author:
            services.add_comment(author, task, COMMENTS[index % len(COMMENTS)])
        made += 1
    return {
        "tasks": Task.objects.count(),
        "advisory_tasks": made,
        "finished_tasks": finished,
        **extras,
    }
