"""Projects, repeating tasks and the workload page."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.clients.views_base import done, render_form
from apps.core.permissions import StaffRequiredMixin

from . import projects, repeating, workload
from .forms import ProjectForm, RepeatingTaskForm
from .models import Project, ProjectTemplate, RepeatingTask
from .views import build_page


class ProjectListView(StaffRequiredMixin, View):
    STATES = [("", "Open"), ("active", "Active"), ("planned", "Planned"), ("on_hold", "On hold"),
              ("done", "Done"), ("all", "All")]  # fmt: skip

    def get(self, request):
        state = request.GET.get("state", "")
        rows = projects.list_projects(state)
        return render(
            request,
            "tasks/projects.html",
            {
                "projects": rows,
                "state": state,
                "states": self.STATES,
                "templates": list(ProjectTemplate.objects.filter(active=True)),
            },
        )


class ProjectCreateView(StaffRequiredMixin, View):
    def _render(self, request, form, status=200):
        return render_form(
            request,
            title="New project",
            form=form,
            action=reverse("tasks:project_new"),
            target="drawer",
            submit="Create project",
            status=status,
            extra="tasks/_client_datalist.html",
            back=reverse("tasks:projects"),
        )

    def get(self, request):
        initial = {"owner": request.user.pk, "state": Project.State.PLANNED}
        template = request.GET.get("template", "")
        if template.isdigit():
            initial["template"] = int(template)
        return self._render(request, ProjectForm(initial=initial))

    def post(self, request):
        form = ProjectForm(request.POST)
        if not form.is_valid():
            return self._render(request, form, 422)
        data = form.cleaned_data
        try:
            project = projects.create_project(
                request.user,
                name=data["name"],
                client=data["client_text"],
                owner=data["owner"],
                state=data["state"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                budget_hours=data["budget_hours"],
                description=data["description"],
                template=data["template"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self._render(request, form, 422)
        return done(request, reverse("tasks:project", args=[project.pk]), "Project created.")


class ProjectView(StaffRequiredMixin, View):
    def get(self, request, pk):
        project = get_object_or_404(Project.objects.select_related("client", "owner"), pk=pk)
        base = reverse("tasks:project", args=[project.pk])
        context = build_page(request, base_url=base, fixed_project=project, default_group="section")
        if getattr(request, "htmx", False) and request.htmx.target == "task-page":
            return render(request, "tasks/_page.html", context)
        context.update(
            project=project,
            progress=projects.progress(project),
            sections=list(project.sections.all()),
        )
        return render(request, "tasks/project.html", context)


class ProjectEditView(StaffRequiredMixin, View):
    def _render(self, request, project, form, status=200):
        return render_form(
            request,
            title=f"Edit {project.name}",
            form=form,
            action=reverse("tasks:project_edit", args=[project.pk]),
            target="drawer",
            status=status,
            extra="tasks/_client_datalist.html",
            back=reverse("tasks:project", args=[project.pk]),
        )

    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        return self._render(request, project, ProjectForm(instance=project))

    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        form = ProjectForm(request.POST, instance=project)
        if not form.is_valid():
            return self._render(request, project, form, 422)
        data = form.cleaned_data
        try:
            projects.update_project(
                request.user,
                project,
                name=data["name"],
                client=data["client_text"],
                owner=data["owner"],
                state=data["state"],
                start_date=data["start_date"],
                end_date=data["end_date"],
                budget_hours=data["budget_hours"],
                description=data["description"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self._render(request, project, form, 422)
        return done(request, reverse("tasks:project", args=[project.pk]), "Project saved.")


class ProjectSectionView(StaffRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(Project, pk=pk)
        try:
            projects.add_section(request.user, project, request.POST.get("name", ""))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect("tasks:project", pk=pk)


# ------------------------------------------------------------------ repeating tasks


class RepeatingListView(StaffRequiredMixin, View):
    def get(self, request):
        rules = RepeatingTask.objects.select_related("client", "owner", "category").annotate(
            made=models.Count("tasks")
        )
        return render(request, "tasks/repeating.html", {"rules": rules})


class RepeatingEditView(StaffRequiredMixin, View):
    def _rule(self, pk):
        return get_object_or_404(RepeatingTask, pk=pk) if pk else None

    def _render(self, request, rule, form, status=200):
        return render_form(
            request,
            title="Edit repeating task" if rule else "New repeating task",
            form=form,
            action=reverse("tasks:repeating_edit", args=[rule.pk])
            if rule
            else reverse("tasks:repeating_new"),
            target="drawer",
            submit="Save" if rule else "Create repeating task",
            status=status,
            extra="tasks/_client_datalist.html",
            back=reverse("tasks:repeating"),
        )

    def get(self, request, pk=None):
        rule = self._rule(pk)
        if rule:
            form = RepeatingTaskForm(instance=rule)
        else:
            initial = {"owner": request.user.pk, "first_date": timezone.localdate()}
            client = request.GET.get("client", "")
            if client.isdigit():
                from apps.clients.models import Client

                found = Client.objects.filter(pk=int(client)).first()
                if found:
                    from .forms import client_label

                    initial["client_text"] = client_label(found)
            form = RepeatingTaskForm(initial=initial)
        return self._render(request, rule, form)

    def post(self, request, pk=None):
        rule = self._rule(pk)
        form = RepeatingTaskForm(request.POST, instance=rule)
        if not form.is_valid():
            return self._render(request, rule, form, 422)
        obj = form.save(commit=False)
        obj.client = form.cleaned_data["client_text"]
        try:
            repeating.save(request.user, obj)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self._render(request, rule, form, 422)
        if rule is None:
            repeating.create_due()
        return done(request, reverse("tasks:repeating"), "Repeating task saved.")


class RepeatingToggleView(StaffRequiredMixin, View):
    def post(self, request, pk):
        rule = get_object_or_404(RepeatingTask, pk=pk)
        rule.active = not rule.active
        rule.save(update_fields=["active", "updated_at"])
        messages.success(request, f"{rule.title} is now {'on' if rule.active else 'off'}.")
        return redirect("tasks:repeating")


# ------------------------------------------------------------------ workload


class WorkloadView(StaffRequiredMixin, View):
    def get(self, request):
        today = timezone.localdate()
        return render(
            request,
            "tasks/workload.html",
            {"rows": workload.build(today), "window": workload.WINDOW_DAYS, "today": today},
        )
