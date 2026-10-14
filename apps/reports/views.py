"""Reports: one index, one page pattern and one export pattern, and the client summary PDF."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps import events
from apps.clients.models import Client
from apps.core.csvexport import csv_response
from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from .catalogue import REPORTS
from .summary import build_pdf


class ReportsIndexView(StaffRequiredMixin, View):
    def get(self, request):
        return render(request, "reports/index.html", {"reports": REPORTS.values()})


def _result(request, key):
    report = REPORTS[key]
    form = report.form(request.GET, request.user)
    data = form.data_or_empty if form.is_bound else {}
    return report, form, report.build(data, request.user)


class ReportView(StaffRequiredMixin, View):
    def get(self, request, key):
        report, form, result = _result(request, key)
        keep = request.GET.copy()
        keep.pop("page", None)
        page = paginate(request, result.rows, per_page=50)
        numeric = [c.numeric for c in result.columns]
        return render(
            request,
            "reports/report.html",
            {
                "report": report,
                "form": form,
                "result": result,
                "page": page,
                "table": [list(zip(row, numeric, strict=True)) for row in page.object_list],
                "keep_query": keep.urlencode(),
            },
        )


class ReportExportView(CapabilityRequiredMixin, View):
    required_rights = ("data.export",)
    require_reauth = True
    reauth_allow_get = False

    def get(self, request, key):
        report, _form, result = _result(request, key)
        response, writer = csv_response(f"{key}.csv")
        writer.writerow([c.label for c in result.columns])
        writer.writerows(result.rows)
        events.record(
            request.user,
            "export.run",
            f"{request.user} exported {len(result.rows)} rows of the {report.title} report to CSV.",
            rows=len(result.rows),
            list=key,
            filters=request.GET.urlencode(),
        )
        return response


class ClientSummaryView(StaffRequiredMixin, View):
    """“Generate report” on the client page: a PDF to download."""

    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        pdf = build_pdf(client, request.user)
        response = HttpResponse(pdf, content_type="application/pdf")
        name = f"{client.reference}-summary.pdf"
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "no-store"
        return response
