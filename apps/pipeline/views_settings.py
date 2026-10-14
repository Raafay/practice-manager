"""Settings: pipeline stages, the quiet rule and the proposal wording."""

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps import events
from apps.clients.views_base import done, render_form
from apps.core.permissions import CapabilityRequiredMixin

from .forms import PipelineSettingsForm, StageForm
from .models import PipelineSettings, PipelineStage


class SettingsMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)


class StageListView(SettingsMixin, View):
    def get(self, request):
        stages = PipelineStage.objects.annotate(uses=Count("prospects"))
        return render(request, "pipeline/settings_stages.html", {"stages": stages})


class StageEditView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200):
        url = (
            reverse("pipeline:stage_edit", args=[instance.pk])
            if instance.pk
            else reverse("pipeline:stage_add")
        )
        return render_form(
            request,
            title=f"Edit {instance.name}" if instance.pk else "New stage",
            form=form,
            action=url,
            status=status,
            back=reverse("pipeline:stages"),
            intro="" if instance.pk else "A new stage is an open stage, between Enquiry and Won.",
        )

    def _instance(self, pk):
        if pk is None:
            last = PipelineStage.objects.filter(is_open=True).order_by("-position").first()
            return PipelineStage(
                is_open=True, position=(last.position + 1) if last else 0, chance=10
            )
        return get_object_or_404(PipelineStage, pk=pk)

    def get(self, request, pk=None):
        instance = self._instance(pk)
        return self._render(request, StageForm(instance=instance), instance)

    def post(self, request, pk=None):
        instance = self._instance(pk)
        form = StageForm(request.POST, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        stage = form.save(commit=False)
        if not stage.pk:
            from django.utils.text import slugify

            base = slugify(stage.name)[:24] or "stage"
            key, n = base, 2
            while PipelineStage.objects.filter(key=key).exists():
                key, n = f"{base}-{n}", n + 1
            stage.key = key
        stage.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} saved the pipeline stage {stage.name}.",
            setting="pipeline_stage",
        )
        return done(request, reverse("pipeline:stages"), f"{stage.name} saved.")


class StageDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        stage = get_object_or_404(PipelineStage, pk=pk)
        if stage.is_won or stage.is_lost or stage.is_on_hold:
            messages.error(request, "Won, Lost and On hold are needed and cannot be removed.")
        elif stage.prospects.exists():
            messages.error(request, "Move the prospects out of this stage first.")
        else:
            stage.delete()
            events.record(
                request.user,
                "setting.changed",
                f"{request.user} removed the pipeline stage {stage.name}.",
                setting="pipeline_stage",
            )
            messages.success(request, f"{stage.name} was removed.")
        return redirect("pipeline:stages")


class PipelineSettingsView(SettingsMixin, View):
    def _render(self, request, form, status=200):
        return render(
            request,
            "pipeline/settings_rules.html",
            {"form": form, "starter": PipelineSettings.load().wording_is_starter},
            status=status,
        )

    def get(self, request):
        return self._render(request, PipelineSettingsForm(instance=PipelineSettings.load()))

    def post(self, request):
        form = PipelineSettingsForm(request.POST, instance=PipelineSettings.load())
        if not form.is_valid():
            return self._render(request, form, 422)
        form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} changed the pipeline and proposal settings.",
            setting="pipeline_settings",
        )
        messages.success(request, "Saved.")
        return redirect("pipeline:rules")
