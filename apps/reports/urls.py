from django.urls import path

from . import views
from .catalogue import REPORTS

app_name = "reports"

urlpatterns = [
    path("reports/", views.ReportsIndexView.as_view(), name="index"),
    path("clients/<int:pk>/summary.pdf", views.ClientSummaryView.as_view(), name="client_summary"),
]
for _key in REPORTS:
    urlpatterns += [
        path(f"reports/{_key}/", views.ReportView.as_view(), {"key": _key}, name=_key),
        path(
            f"reports/{_key}/export/",
            views.ReportExportView.as_view(),
            {"key": _key},
            name=f"{_key}_export",
        ),
    ]
