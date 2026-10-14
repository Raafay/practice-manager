"""Owner pages for data protection: the retention report, a subject access export and
removing a person for good. Each needs retention.manage (the owner)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.core.permissions import CapabilityRequiredMixin

from . import retention
from .models import Contact


class RetentionAccess(CapabilityRequiredMixin):
    required_rights = ("retention.manage",)


class RetentionReportView(RetentionAccess, View):
    def get(self, request):
        return render(request, "clients/retention.html", {"report": retention.build_report()})


class ContactExportView(RetentionAccess, View):
    """Everything held about one person, as a ZIP. A download, so the password is
    asked for again even though it is a GET."""

    require_reauth = True
    reauth_allow_get = False

    def get(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        name, data = retention.subject_access_zip(request.user, contact)
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "private, no-store"
        return response


class ContactPurgeView(RetentionAccess, View):
    require_reauth = True
    template_name = "clients/contact_purge.html"

    def _render(self, request, contact, error="", status=200):
        context = {
            "contact": contact,
            "blocked_reason": retention.purge_block(contact),
            "error": error,
        }
        return render(request, self.template_name, context, status=status)

    def get(self, request, pk):
        return self._render(request, get_object_or_404(Contact, pk=pk))

    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        try:
            retention.purge_contact(request.user, contact, request.POST.get("typed_name", ""))
        except ValidationError as error:
            return self._render(request, contact, " ".join(error.messages), status=422)
        messages.success(request, "The person's records and files were removed for good.")
        return redirect("clients:retention")
