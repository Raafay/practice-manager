"""Projects: several-step advisory work, optionally made from a template."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.urls import reverse

from apps import events
from apps.accounts.models import User
from apps.core.dates import next_working_day

from . import services
from .models import (
    Project,
    ProjectSection,
    ProjectTemplate,
    Task,
    TaskKind,
)


def project_url(project: Project) -> str:
    return reverse("tasks:project", args=[project.pk])


def _record(actor, verb: str, summary: str, project: Project, **data):
    return events.record(actor, verb, summary, client=project.client, target=project, **data)


def create_project(
    actor,
    *,
    name: str,
    client=None,
    owner: User | None = None,
    state: str = Project.State.PLANNED,
    start_date: date | None = None,
    end_date: date | None = None,
    budget_hours: Decimal | None = None,
    description: str = "",
    template: ProjectTemplate | None = None,
) -> Project:
    """Make a project. With a template, its sections and tasks are made too."""
    name = name.strip()
    if not name:
        raise ValidationError("Give the project a name.")
    if state not in Project.State.values:
        raise ValidationError("Choose a state.")
    if end_date and start_date and end_date < start_date:
        raise ValidationError("The end date is before the start date.")
    if template is not None and start_date is None:
        raise ValidationError("A project made from a template needs a start date.")
    with transaction.atomic():
        project = Project.objects.create(
            name=name[:200],
            client=client,
            owner=owner,
            state=state,
            start_date=start_date,
            end_date=end_date,
            budget_hours=budget_hours,
            description=description.strip(),
            template=template,
            created_by=actor,
        )
        made = 0
        if template is not None:
            made = _fill_from_template(actor, project, template)
        _record(
            actor,
            "project.created",
            f"{services.who(actor)} created the project {project.name}"
            + (f" for {client.name}" if client else "")
            + (f" from the template {template.name} ({made} tasks)" if template else "")
            + ".",
            project,
        )
    if owner is not None and actor is not None and owner.pk != actor.pk:
        events.notify(
            owner,
            f"{services.who(actor)} made you owner of the project {project.name}.",
            project_url(project),
            kind="assigned",
        )
    return project


def _fill_from_template(actor, project: Project, template: ProjectTemplate) -> int:
    sections = {}
    for position, section in enumerate(template.sections.all(), 1):
        sections[section.pk] = ProjectSection.objects.create(
            project=project, name=section.name, position=position * 10
        )
    made = 0
    for item in template.tasks.select_related("category").order_by("position", "id"):
        planned = next_working_day(project.start_date + timedelta(days=item.day_offset))
        task = services.create_task(
            actor,
            title=item.title,
            client=project.client,
            kind=TaskKind.ADVISORY,
            category=item.category,
            owner=project.owner,
            target_date=planned,
            start_date=project.start_date,
            estimate_minutes=item.estimate_minutes,
            source=Task.Source.PROJECT_TEMPLATE,
            project=project,
            section=sections[item.section_id],
            notify=False,
        )
        Task.objects.filter(pk=task.pk).update(position=(made + 1) * services.POSITION_GAP)
        made += 1
    return made


def update_project(actor, project: Project, **values) -> Project:
    allowed = {
        "name", "client", "owner", "state", "start_date", "end_date", "budget_hours", "description",
    }  # fmt: skip
    changed = {}
    for key, value in values.items():
        if key not in allowed:
            raise ValidationError("That cannot be changed.")
        if getattr(project, key) != value:
            changed[key] = {"old": str(getattr(project, key) or ""), "new": str(value or "")}
            setattr(project, key, value)
    if not changed:
        return project
    if project.end_date and project.start_date and project.end_date < project.start_date:
        raise ValidationError("The end date is before the start date.")
    if not project.name.strip():
        raise ValidationError("Give the project a name.")
    project.save()
    if "client" in changed:
        Task.objects.filter(project=project).update(client=project.client)
    _record(
        actor,
        "project.changed",
        f"{services.who(actor)} changed the project {project.name} ({', '.join(sorted(changed))}).",
        project,
        changes=changed,
    )
    return project


def add_section(actor, project: Project, name: str) -> ProjectSection:
    name = name.strip()
    if not name:
        raise ValidationError("Give the section a name.")
    last = project.sections.order_by("-position").first()
    section = ProjectSection.objects.create(
        project=project, name=name[:120], position=(last.position + 10) if last else 10
    )
    _record(
        actor,
        "project.section_added",
        f"{services.who(actor)} added the section {section.name} to {project.name}.",
        project,
    )
    return section


def progress(project: Project) -> dict:
    """Done and total tasks (cancelled ones left out) and the planned and budgeted hours."""
    totals = (
        Task.objects.live()
        .filter(project=project)
        .aggregate(
            total=Count("id"),
            done=Count("id", filter=Q(status__is_done=True)),
            minutes=Sum("estimate_minutes"),
        )
    )
    total, done = totals["total"], totals["done"]
    minutes = totals["minutes"] or 0
    return {
        "total": total,
        "done": done,
        "percent": round(done * 100 / total) if total else 0,
        "planned_hours": Decimal(minutes) / Decimal(60),
        "budget_hours": project.budget_hours,
        "over_budget": bool(
            project.budget_hours and Decimal(minutes) / Decimal(60) > project.budget_hours
        ),
    }


def list_projects(state: str = ""):
    projects = Project.objects.select_related("client", "owner")
    if state in Project.State.values:
        projects = projects.filter(state=state)
    elif state != "all":
        projects = projects.exclude(state=Project.State.DONE)
    rows = list(
        projects.annotate(
            n_total=Count("tasks", filter=Q(tasks__cancelled_at__isnull=True), distinct=True),
            n_done=Count(
                "tasks",
                filter=Q(tasks__cancelled_at__isnull=True, tasks__status__is_done=True),
                distinct=True,
            ),
        )
    )
    for project in rows:
        project.percent = round(project.n_done * 100 / project.n_total) if project.n_total else 0
    return rows
