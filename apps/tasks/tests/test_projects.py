from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent, Notification
from apps.tasks import projects, services
from apps.tasks.models import Project, ProjectTemplate, Task

from .factories import make_task

pytestmark = pytest.mark.django_db

START = date(2026, 10, 12)  # a Monday

TEMPLATES = [
    "Finance function health check",
    "New starter finance training (12 weeks)",
    "Internal controls review",
    "Insurance renewal review",
]


def template(name="Finance function health check"):
    return ProjectTemplate.objects.get(name=name)


def test_the_four_templates_are_seeded_with_realistic_task_lists():
    assert list(ProjectTemplate.objects.values_list("name", flat=True)) == TEMPLATES
    for t in ProjectTemplate.objects.all():
        assert t.sections.count() >= 3 and t.tasks.count() >= 7, t.name
        assert all(item.estimate_minutes and item.category for item in t.tasks.all())
    training = template("New starter finance training (12 weeks)")
    assert max(item.day_offset for item in training.tasks.all()) >= 77  # runs about 12 weeks


def test_a_project_from_a_template_has_the_right_tasks_sections_and_dates():
    boss, helper = owner(name="Ann Owner"), staff(name="Bob Staff")
    client_row = ClientFactory(name="Acorn Ltd")
    project = projects.create_project(
        boss,
        name="Health check",
        client=client_row,
        owner=helper,
        start_date=START,
        template=template(),
    )
    t = template()
    assert project.sections.count() == t.sections.count()
    assert [s.name for s in project.sections.all()] == [s.name for s in t.sections.all()]
    tasks = list(project.tasks.order_by("position", "id"))
    assert len(tasks) == t.tasks.count()
    assert all(
        task.client == client_row
        and task.owner == helper
        and task.source == Task.Source.PROJECT_TEMPLATE
        and task.kind == "advisory"
        and task.section.project == project
        for task in tasks
    )
    by_title = {task.title: task for task in tasks}
    # Offsets 0, 3, 7 and 14 days from Monday 12/10/2026.
    assert by_title["Kick-off call with the director"].target_date == date(2026, 10, 12)
    assert by_title[
        "Collect the chart of accounts, policies and last two sets of accounts"
    ].target_date == date(2026, 10, 15)
    assert by_title["Map who does what in the finance team"].target_date == date(2026, 10, 19)
    assert by_title["Review month-end close and reconciliations"].target_date == date(2026, 10, 26)
    first = by_title["Kick-off call with the director"]
    assert first.section.name == "Understand the business" and first.estimate_minutes == 60
    assert first.category.name == "Operations"
    assert ActivityEvent.objects.filter(verb="project.created").count() == 1


def test_template_dates_that_fall_on_a_weekend_move_to_the_next_working_day():
    project = projects.create_project(
        owner(),
        name="Weekend start",
        start_date=date(2026, 10, 17),  # a Saturday
        template=template(),
    )
    kickoff = project.tasks.get(title="Kick-off call with the director")
    assert kickoff.target_date == date(2026, 10, 19)


def test_a_template_needs_a_start_date():
    with pytest.raises(ValidationError):
        projects.create_project(owner(), name="No start", template=template())


def test_the_project_owner_is_told_once_not_once_per_task():
    boss, helper = owner(), staff()
    projects.create_project(boss, name="P", owner=helper, start_date=START, template=template())
    assert Notification.objects.filter(user=helper).count() == 1
    mine = projects.create_project(
        boss, name="Mine", owner=boss, start_date=START, template=template()
    )
    assert Notification.objects.filter(user=boss).count() == 0 and mine.tasks.exists()


def test_progress_counts_done_tasks_and_hours():
    boss = owner()
    project = projects.create_project(
        boss, name="P", owner=boss, start_date=START, budget_hours=Decimal("1"),
        template=template("Insurance renewal review"),
    )  # fmt: skip
    total = project.tasks.count()
    for task in list(project.tasks.all())[:3]:
        services.complete(boss, task)
    summary = projects.progress(project)
    assert summary["total"] == total and summary["done"] == 3
    assert summary["percent"] == round(300 / total)
    assert summary["over_budget"] is True and summary["planned_hours"] > 1


def test_cancelled_tasks_do_not_count_towards_progress():
    boss = owner()
    project = projects.create_project(boss, name="P", start_date=START)
    one = make_task(boss, title="One", project=project)
    make_task(boss, title="Two", project=project)
    services.cancel(boss, one)
    assert projects.progress(project)["total"] == 1


def test_the_project_pages_work(client):
    boss = owner(name="Ann Owner")
    sign_in(client, boss)
    client_row = ClientFactory(name="Acorn Ltd")
    project = projects.create_project(
        boss, name="Health check", client=client_row, owner=boss, start_date=START,
        template=template(),
    )  # fmt: skip
    listing = client.get(reverse("tasks:projects")).content.decode()
    assert "Health check" in listing and "Start from a template" in listing
    page = client.get(reverse("tasks:project", args=[project.pk])).content.decode()
    assert "Understand the business" in page and "Kick-off call" in page
    board = client.get(reverse("tasks:project", args=[project.pk]) + "?layout=board&by=section")
    assert 'data-board="section"' in board.content.decode()
    other = projects.create_project(boss, name="Elsewhere", start_date=START)
    assert (
        "Kick-off call"
        not in client.get(reverse("tasks:project", args=[other.pk])).content.decode()
    )


def test_creating_and_editing_a_project_through_the_forms(client):
    boss = owner(name="Ann Owner")
    sign_in(client, boss)
    template_row = template("Internal controls review")
    response = client.post(
        reverse("tasks:project_new"),
        {
            "template": template_row.pk, "name": "Controls", "client_text": "", "owner": boss.pk,
            "state": "planned", "start_date": "2026-10-12", "end_date": "", "budget_hours": "20",
            "description": "",
        },
    )  # fmt: skip
    assert response.status_code == 302
    project = Project.objects.get(name="Controls")
    assert project.tasks.count() == template_row.tasks.count()
    client.post(
        reverse("tasks:project_edit", args=[project.pk]),
        {"name": "Controls v2", "client_text": "", "owner": boss.pk, "state": "active",
         "start_date": "2026-10-12", "end_date": "", "budget_hours": "20", "description": ""},
    )  # fmt: skip
    project.refresh_from_db()
    assert project.name == "Controls v2" and project.state == "active"
    client.post(reverse("tasks:project_section_add", args=[project.pk]), {"name": "Wrap up"})
    assert project.sections.filter(name="Wrap up").exists()
    bad = client.post(
        reverse("tasks:project_new"),
        {"name": "Bad", "start_date": "2026-10-12", "end_date": "2026-10-01", "state": "planned"},
    )
    assert bad.status_code == 422


def test_a_new_task_can_be_added_inside_a_project(client):
    boss = owner()
    sign_in(client, boss)
    project = projects.create_project(boss, name="P", client=ClientFactory(), start_date=START)
    section = projects.add_section(boss, project, "Phase 1")
    form = client.get(
        reverse("tasks:new") + f"?project={project.pk}&section={section.pk}"
    ).content.decode()
    assert f'name="project" value="{project.pk}"' in form
    client.post(
        reverse("tasks:new"),
        {"title": "In phase 1", "kind": "advisory", "project": project.pk, "section": section.pk,
         "owner": boss.pk},
    )  # fmt: skip
    task = Task.objects.get(title="In phase 1")
    assert task.project == project and task.section == section and task.client == project.client
