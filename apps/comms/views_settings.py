"""Settings: message templates and reminder schedules."""

from datetime import timedelta

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.clients.models import Client
from apps.core.permissions import CapabilityRequiredMixin
from apps.services.models import Deadline

from . import merge, services
from .forms import ScheduleForm, TemplateForm
from .models import Channel, MessageTemplate, QueuedMessage, ReminderSchedule
from .sms import sms_enabled


class SettingsMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)


def _log(request, text: str, setting: str):
    events.record(request.user, "setting.changed", f"{request.user} {text}", setting=setting)


# ------------------------------------------------------------------ templates


class TemplateListView(SettingsMixin, View):
    def get(self, request):
        items = MessageTemplate.objects.all()
        if not sms_enabled():
            items = items.exclude(channel=Channel.SMS)
        return render(request, "comms/settings_templates.html", {"items": items})


class TemplateEditView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200, preview=None):
        client_id = request.GET.get("client") or request.POST.get("preview_client") or ""
        clients = Client.objects.not_archived().order_by("name")[:200]
        grouped: dict[str, list] = {}
        for name, (group, label) in merge.FIELDS.items():
            grouped.setdefault(group, []).append((name, label))
        context = {
            "form": form,
            "instance": instance,
            "clients": clients,
            "client_id": str(client_id),
            "field_groups": grouped,
            "preview": preview,
        }
        return render(request, "comms/template_form.html", context, status=status)

    def _preview(self, instance, client_id, user=None):
        client = Client.objects.filter(pk=client_id).first() if str(client_id).isdigit() else None
        if client is None:
            client = Client.objects.not_archived().order_by("name").first()
        if client is None or not instance.pk:
            return None
        # A real open deadline if the client has one, else a labelled sample.
        deadline = client.deadlines.filter(status="open").order_by("due_date").first()
        if deadline is None:
            today = timezone.localdate()
            deadline = Deadline(
                label="Sample deadline", due_date=today + timedelta(days=14), period_end=today
            )
        ctx = services.build_context(client, user=user, deadline=deadline)
        subject, html, text, problems = services.render_template(instance, ctx)
        return {
            "client": client,
            "subject": subject,
            "html": html,
            "text": text,
            "problems": problems,
        }

    def get(self, request, pk=None):
        instance = get_object_or_404(MessageTemplate, pk=pk) if pk else MessageTemplate()
        form = TemplateForm(instance=instance, can_set_auto=request.user.is_owner)
        return self._render(
            request,
            form,
            instance,
            preview=self._preview(instance, request.GET.get("client"), request.user),
        )

    def post(self, request, pk=None):
        instance = get_object_or_404(MessageTemplate, pk=pk) if pk else MessageTemplate()
        form = TemplateForm(request.POST, instance=instance, can_set_auto=request.user.is_owner)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        creating = instance.pk is None
        saved = form.save()
        _log(
            request,
            f"{'added' if creating else 'changed'} the message template “{saved.name}”.",
            "message_template",
        )
        unknown = merge.unknown_fields(saved.subject, saved.body)
        if unknown:
            messages.warning(
                request,
                "Saved, but these merge fields are not known and will block sending: "
                + ", ".join(unknown),
            )
        else:
            messages.success(request, "Template saved.")
        return redirect("comms:template_edit", pk=saved.pk)


class TemplateDeleteView(SettingsMixin, View):
    def post(self, request, pk):
        template = get_object_or_404(MessageTemplate, pk=pk)
        if template.system:
            messages.error(request, "System templates cannot be deleted. Switch it off instead.")
        elif (
            template.schedules.exists() or QueuedMessage.objects.filter(template=template).exists()
        ):
            messages.error(request, "This template has been used. Switch it off instead.")
        else:
            name = template.name
            template.delete()
            _log(request, f"deleted the message template “{name}”.", "message_template")
            messages.success(request, f"“{name}” deleted.")
        return redirect("comms:templates")


class TemplateToggleView(SettingsMixin, View):
    def post(self, request, pk):
        template = get_object_or_404(MessageTemplate, pk=pk)
        template.active = not template.active
        template.save(update_fields=["active", "updated_at"])
        _log(
            request,
            f"switched the message template “{template.name}” "
            f"{'on' if template.active else 'off'}.",
            "message_template",
        )
        return redirect("comms:templates")


# ------------------------------------------------------------------ schedules


class ScheduleListView(SettingsMixin, View):
    def get(self, request):
        items = ReminderSchedule.objects.select_related("template")
        if not sms_enabled():
            items = items.exclude(template__channel=Channel.SMS)
        return render(request, "comms/settings_reminders.html", {"items": items})


class ScheduleEditView(SettingsMixin, View):
    def _render(self, request, form, instance, status=200):
        return render(
            request, "comms/schedule_form.html", {"form": form, "instance": instance}, status=status
        )

    def get(self, request, pk):
        instance = get_object_or_404(ReminderSchedule, pk=pk)
        return self._render(
            request, ScheduleForm(instance=instance, can_set_auto=request.user.is_owner), instance
        )

    def post(self, request, pk):
        instance = get_object_or_404(ReminderSchedule, pk=pk)
        form = ScheduleForm(request.POST, instance=instance, can_set_auto=request.user.is_owner)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        saved = form.save()
        mode = form.cleaned_data.get("send_mode")
        if request.user.is_owner and mode and mode != saved.template.send_mode:
            saved.template.send_mode = mode
            saved.template.save(update_fields=["send_mode", "updated_at"])
            _log(
                request,
                f"set the template “{saved.template.name}” to "
                f"{saved.template.get_send_mode_display().lower()}.",
                "message_template",
            )
        _log(request, f"changed the reminder “{saved.name}”.", "reminder_schedule")
        messages.success(request, "Reminder saved.")
        return redirect("comms:reminders")


class ScheduleToggleView(SettingsMixin, View):
    def post(self, request, pk):
        schedule = get_object_or_404(ReminderSchedule, pk=pk)
        schedule.active = not schedule.active
        schedule.save(update_fields=["active", "updated_at"])
        _log(
            request,
            f"switched the reminder “{schedule.name}” {'on' if schedule.active else 'off'}.",
            "reminder_schedule",
        )
        return redirect("comms:reminders")


__all__ = ["Http404", "reverse"]
