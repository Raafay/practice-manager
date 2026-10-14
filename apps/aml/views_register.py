from django.shortcuts import render
from django.urls import reverse
from django.views import View

from apps import events
from apps.core.csvexport import csv_response
from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from .register import RegisterFilterForm, build_rows


class RegisterView(StaffRequiredMixin, View):
    def get(self, request):
        form = RegisterFilterForm(request.GET)
        rows = build_rows(form)
        keep = request.GET.copy()
        keep.pop("page", None)
        return render(
            request,
            "aml/register.html",
            {
                "form": form,
                "page": paginate(request, rows, per_page=50),
                "total": len(rows),
                "keep_query": keep.urlencode(),
                "export_url": reverse("aml:register_export"),
            },
        )


class RegisterExportView(CapabilityRequiredMixin, View):
    required_rights = ("data.export",)
    require_reauth = True
    reauth_allow_get = False

    def get(self, request):
        form = RegisterFilterForm(request.GET)
        rows = build_rows(form)
        response, writer = csv_response("aml-register.csv")
        writer.writerow(
            [
                "Client",
                "Reference",
                "Client status",
                "Risk level",
                "AML state",
                "Last assessed",
                "Next review",
                "People verified",
                "People to identify",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.client.name,
                    r.client.reference,
                    r.client.get_status_display(),
                    r.level_label,
                    r.state_label,
                    r.last_assessed,
                    r.next_review,
                    r.verified,
                    r.total,
                ]
            )
        events.record(
            request.user,
            "export.run",
            f"{request.user} exported {len(rows)} rows of the AML register to CSV.",
            rows=len(rows),
            list="aml register",
        )
        return response
