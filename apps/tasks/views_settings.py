"""Settings: task statuses, task categories, and the templates under each service."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps import events
from apps.clients.views_base import done, render_form
from apps.core.permissions import CapabilityRequiredMixin
from apps.services.models import Service

from . import services
from .forms import CategoryForm, MergeForm, StatusForm, StepFormSet, TemplateForm
from .models import TaskCategory, TaskStatus, TaskTemplate


class SettingsMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)


def _log(request, text: str, setting: str):
    events.record(request.user, "setting.changed", f"{request.user} {text}", setting=setting)


# ------------------------------------------------------------------ statuses


class StatusListView(SettingsMixin, View):
    def get(self, request):
        items = TaskStatus.objects.annotate(uses=Count("tasks"))
        return render(request, "tasks/settings_statuses.html", {"items": items})


class StatusEditView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200):
        url = (
            reverse("tasks:status_edit", args=[instance.pk])
            if instance.pk
            else reverse("tasks:status_add")
        )
        return render_form(
            request,
            title=f"Edit {instance.name}" if instance.pk else "New status",
            form=form,
            action=url,
            target="drawer",
            status=status,
        )

    def get(self, request, pk=None):
        instance = get_object_or_404(TaskStatus, pk=pk) if pk else TaskStatus(colour="#64748b")
        return self._render(request, StatusForm(instance=instance), instance)

    def post(self, request, pk=None):
        instance = get_object_or_404(TaskStatus, pk=pk) if pk else TaskStatus()
        if not pk:
            instance.position = (
                TaskStatus.objects.order_by("-position").first() or instance
            ).position + 10
        form = StatusForm(request.POST, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        creating = instance.pk is None
        saved = form.save()
        _log(
            request,
            f"{'added' if creating else 'changed'} the task status “{saved.name}”.",
            "task_status",
        )
        return done(request, reverse("tasks:statuses"), "Status saved.")


class StatusDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        status = get_object_or_404(TaskStatus, pk=pk)
        if not services.can_delete_status(status):
            messages.error(
                request,
                f"“{status.name}” is used by tasks. Switch it off, or merge it into "
                "another status.",
            )
        elif status.is_default:
            messages.error(request, "Choose another status as the default first.")
        else:
            name = status.name
            status.delete()
            _log(request, f"deleted the task status “{name}”.", "task_status")
            messages.success(request, f"“{name}” deleted.")
        return redirect("tasks:statuses")


class StatusMoveView(SettingsMixin, View):
    def post(self, request, pk, direction):
        return _move(request, TaskStatus, pk, direction, "tasks:statuses", "task_status")


class StatusMergeView(SettingsMixin, View):
    def _form(self, request, instance, data=None):
        others = TaskStatus.objects.filter(is_done=instance.is_done, active=True).exclude(
            pk=instance.pk
        )
        return MergeForm(data, queryset=others)

    def _render(self, request, form, instance, status=200):
        return render_form(
            request,
            title=f"Merge {instance.name}",
            form=form,
            action=reverse("tasks:status_merge", args=[instance.pk]),
            target="drawer",
            submit="Merge",
            status=status,
            intro="Every task with this status moves to the one you choose, and this status "
            "is switched off.",
        )

    def get(self, request, pk):
        instance = get_object_or_404(TaskStatus, pk=pk)
        return self._render(request, self._form(request, instance), instance)

    def post(self, request, pk):
        instance = get_object_or_404(TaskStatus, pk=pk)
        form = self._form(request, instance, request.POST)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        try:
            with transaction.atomic():
                services.merge_status(request.user, instance, form.cleaned_data["into"])
        except ValidationError as exc:
            form.add_error(None, exc)
            return self._render(request, form, instance, 422)
        return done(request, reverse("tasks:statuses"), "Status merged.")


# ------------------------------------------------------------------ categories


class CategoryListView(SettingsMixin, View):
    def get(self, request):
        items = TaskCategory.objects.annotate(uses=Count("tasks"))
        return render(request, "tasks/settings_categories.html", {"items": items})


class CategoryEditView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200):
        url = (
            reverse("tasks:category_edit", args=[instance.pk])
            if instance.pk
            else reverse("tasks:category_add")
        )
        return render_form(
            request,
            title=f"Edit {instance.name}" if instance.pk else "New category",
            form=form,
            action=url,
            target="drawer",
            status=status,
        )

    def get(self, request, pk=None):
        instance = get_object_or_404(TaskCategory, pk=pk) if pk else TaskCategory(colour="#64748b")
        return self._render(request, CategoryForm(instance=instance), instance)

    def post(self, request, pk=None):
        instance = get_object_or_404(TaskCategory, pk=pk) if pk else TaskCategory()
        if not pk:
            top = TaskCategory.objects.order_by("-position").first()
            instance.position = (top.position if top else 0) + 10
        form = CategoryForm(request.POST, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        creating = instance.pk is None
        saved = form.save()
        _log(
            request,
            f"{'added' if creating else 'changed'} the task category “{saved.name}”.",
            "task_category",
        )
        return done(request, reverse("tasks:categories"), "Category saved.")


class CategoryDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(TaskCategory, pk=pk)
        if not services.can_delete_category(category):
            messages.error(
                request,
                f"“{category.name}” is in use. Switch it off, or merge it into another category.",
            )
        else:
            name = category.name
            category.delete()
            _log(request, f"deleted the task category “{name}”.", "task_category")
            messages.success(request, f"“{name}” deleted.")
        return redirect("tasks:categories")


class CategoryMoveView(SettingsMixin, View):
    def post(self, request, pk, direction):
        return _move(request, TaskCategory, pk, direction, "tasks:categories", "task_category")


class CategoryMergeView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200):
        return render_form(
            request,
            title=f"Merge {instance.name}",
            form=form,
            action=reverse("tasks:category_merge", args=[instance.pk]),
            target="drawer",
            submit="Merge",
            status=status,
            intro="Every task and template in this category moves to the one you choose, "
            "and this category is switched off.",
        )

    def get(self, request, pk):
        instance = get_object_or_404(TaskCategory, pk=pk)
        others = TaskCategory.objects.filter(active=True).exclude(pk=instance.pk)
        return self._render(request, MergeForm(queryset=others), instance)

    def post(self, request, pk):
        instance = get_object_or_404(TaskCategory, pk=pk)
        others = TaskCategory.objects.filter(active=True).exclude(pk=instance.pk)
        form = MergeForm(request.POST, queryset=others)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        with transaction.atomic():
            services.merge_category(request.user, instance, form.cleaned_data["into"])
        return done(request, reverse("tasks:categories"), "Category merged.")


def _move(request, model, pk, direction, url_name, setting):
    if direction not in ("up", "down"):
        raise Http404
    ordered = list(model.objects.all())
    index = next((i for i, item in enumerate(ordered) if item.pk == pk), None)
    if index is None:
        raise Http404
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(ordered):
        ordered[index], ordered[swap] = ordered[swap], ordered[index]
        for position, item in enumerate(ordered, start=1):
            if item.position != position * 10:
                item.position = position * 10
                item.save(update_fields=["position", "updated_at"])
        _log(request, f"reordered the {setting.replace('_', ' ')}s.", setting)
    return redirect(url_name)


# ------------------------------------------------------------------ templates under a service


class ServiceTemplatesView(SettingsMixin, View):
    def get(self, request, pk):
        service = get_object_or_404(Service, pk=pk)
        templates = service.task_templates.select_related("category").prefetch_related("steps")
        return render(
            request,
            "tasks/settings_templates.html",
            {"service": service, "templates": templates},
        )


class TemplateEditView(SettingsMixin, View):
    def _context(self, service, instance, form, formset):
        return {"service": service, "template": instance, "form": form, "formset": formset}

    def _service_and_instance(self, pk, template_pk):
        if template_pk:
            instance = get_object_or_404(
                TaskTemplate.objects.select_related("service"), pk=template_pk
            )
            return instance.service, instance
        return get_object_or_404(Service, pk=pk), TaskTemplate()

    def get(self, request, pk=None, template_pk=None):
        service, instance = self._service_and_instance(pk, template_pk)
        form = TemplateForm(instance=instance, service=service)
        formset = StepFormSet(instance=instance, prefix="steps")
        return render(
            request, "tasks/template_form.html", self._context(service, instance, form, formset)
        )

    def post(self, request, pk=None, template_pk=None):
        service, instance = self._service_and_instance(pk, template_pk)
        form = TemplateForm(request.POST, instance=instance, service=service)
        formset = StepFormSet(request.POST, instance=instance, prefix="steps")
        if not (form.is_valid() and formset.is_valid()):
            return render(
                request,
                "tasks/template_form.html",
                self._context(service, instance, form, formset),
                status=422,
            )
        creating = instance.pk is None
        with transaction.atomic():
            saved = form.save(commit=False)
            saved.service = service
            if creating:
                top = service.task_templates.order_by("-position").first()
                saved.position = (top.position if top else 0) + 10
            saved.save()
            formset.instance = saved
            formset.save()
        _log(
            request,
            f"{'added' if creating else 'changed'} the task template “{saved.name_pattern}” "
            f"for {service.name}.",
            "task_template",
        )
        messages.success(request, "Template saved.")
        return redirect("tasks:service_templates", pk=service.pk)
