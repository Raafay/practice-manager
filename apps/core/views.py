from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps import events
from apps.events.services import changes, snapshot

from .forms_settings import PracticeDetailsForm, SecuritySettingsForm
from .models import PracticeSettings
from .permissions import CapabilityRequiredMixin, StaffRequiredMixin


class OverviewView(StaffRequiredMixin, TemplateView):
    template_name = "core/overview.html"


class SettingsIndexView(StaffRequiredMixin, TemplateView):
    template_name = "core/settings_index.html"


class StyleguideView(StaffRequiredMixin, TemplateView):
    template_name = "core/styleguide.html"

    def get_context_data(self, **kwargs):
        from apps.accounts.models import User

        context = super().get_context_data(**kwargs)
        context["tab"] = self.request.GET.get("tab", "info")
        context["people"] = User.objects.staff().filter(is_active=True)[:5]
        context["sample_rows"] = [
            {
                "name": "Annual accounts",
                "owner": "Sam",
                "due": "31/12/2026",
                "status": ("Due soon", "amber"),
            },
            {
                "name": "VAT return",
                "owner": "Jordan",
                "due": "07/11/2026",
                "status": ("Overdue", "red"),
            },
            {
                "name": "Confirmation statement",
                "owner": "Ellis",
                "due": "03/11/2026",
                "status": ("Done", "green"),
            },
        ]
        return context


class StyleguideDemoView(StaffRequiredMixin, TemplateView):
    """Content for the drawer and modal examples, loaded with HTMX."""

    def get_template_names(self):
        kind = self.kwargs["kind"]
        if kind not in {"drawer", "modal"}:
            raise Http404
        return [f"core/_styleguide_{kind}.html"]

    def post(self, request, *args, **kwargs):
        messages.success(request, "Saved. This is a success toast.")
        return redirect(reverse("core:styleguide") + "#toasts")


class PracticeSettingsView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)
    template_name = "core/practice_settings.html"
    fields = PracticeDetailsForm.Meta.fields

    def get(self, request):
        form = PracticeDetailsForm(instance=PracticeSettings.load())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        practice = PracticeSettings.objects.get_or_create(pk=1)[0]
        before = snapshot(practice, self.fields)
        form = PracticeDetailsForm(request.POST, request.FILES, instance=practice)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=422)
        practice = form.save()
        diff = changes(before, snapshot(practice, self.fields))
        if diff:
            events.record(
                request.user,
                "settings.changed",
                f"{request.user} changed the practice details.",
                target=practice,
                changes=diff,
            )
        messages.success(request, "Practice details saved.")
        return redirect("core:practice_settings")


class SecuritySettingsView(CapabilityRequiredMixin, View):
    required_rights = ("users.manage",)
    require_reauth = True
    template_name = "core/security_settings.html"
    fields = SecuritySettingsForm.Meta.fields

    def get(self, request):
        form = SecuritySettingsForm(instance=PracticeSettings.load())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        practice = PracticeSettings.objects.get_or_create(pk=1)[0]
        before = snapshot(practice, self.fields)
        form = SecuritySettingsForm(request.POST, instance=practice)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=422)
        practice = form.save()
        diff = changes(before, snapshot(practice, self.fields))
        if diff:
            events.record(
                request.user,
                "settings.changed",
                f"{request.user} changed sign-in and session settings.",
                target=practice,
                changes=diff,
            )
        messages.success(request, "Sign-in settings saved.")
        return redirect("core:security_settings")


class PracticeLogoView(StaffRequiredMixin, View):
    """The logo has no public address. It is served to signed-in staff only."""

    def get(self, request):
        practice = PracticeSettings.load()
        if not practice.logo:
            raise Http404
        response = FileResponse(
            practice.logo.open("rb"),
            content_type=practice.logo_content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, max-age=300"
        return response


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    # No context processors: the database may be the thing that failed.
    from django.http import HttpResponseServerError
    from django.template import loader

    return HttpResponseServerError(loader.get_template("500.html").render())
