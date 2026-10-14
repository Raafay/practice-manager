from django.urls import path

from . import views

app_name = "services"

urlpatterns = [
    # Settings: the catalogue
    path("settings/services/", views.ServiceListView.as_view(), name="list"),
    path("settings/services/add/", views.ServiceEditView.as_view(), name="add"),
    path("settings/services/<int:pk>/edit/", views.ServiceEditView.as_view(), name="edit"),
    path(
        "settings/services/<int:pk>/move/<str:direction>/",
        views.ServiceMoveView.as_view(),
        name="move",
    ),
    path("settings/services/<int:pk>/toggle/", views.ServiceToggleView.as_view(), name="toggle"),
    # The Services panel on a client
    path("clients/<int:pk>/services/", views.PanelView.as_view(), name="panel"),
    path(
        "clients/<int:pk>/services/<int:service_pk>/on/",
        views.SwitchOnView.as_view(),
        name="switch_on",
    ),
    path(
        "clients/<int:pk>/client-services/<int:cs_pk>/settings/",
        views.ServiceSettingsView.as_view(),
        name="settings",
    ),
    path(
        "clients/<int:pk>/client-services/<int:cs_pk>/off/",
        views.SwitchOffView.as_view(),
        name="switch_off",
    ),
    path("clients/<int:pk>/client-services/<int:cs_pk>/fee/", views.FeeView.as_view(), name="fee"),
    # The Deadlines tab and its actions
    path(
        "clients/<int:pk>/deadlines/", views.ClientDeadlinesView.as_view(), name="client_deadlines"
    ),
    path(
        "clients/<int:pk>/deadlines/<int:deadline_pk>/done/",
        views.DeadlineActionView.as_view(action="done"),
        name="deadline_done",
    ),
    path(
        "clients/<int:pk>/deadlines/<int:deadline_pk>/not-required/",
        views.DeadlineActionView.as_view(action="not_required"),
        name="deadline_not_required",
    ),
    path(
        "clients/<int:pk>/deadlines/<int:deadline_pk>/reopen/",
        views.DeadlineActionView.as_view(action="reopen"),
        name="deadline_reopen",
    ),
    path(
        "clients/<int:pk>/deadlines/<int:deadline_pk>/date/",
        views.DeadlineActionView.as_view(action="date"),
        name="deadline_date",
    ),
    # Reports
    path("reports/deadlines/", views.DeadlineReportView.as_view(), name="report_deadlines"),
    path(
        "reports/deadlines/export/",
        views.DeadlineReportExportView.as_view(),
        name="report_deadlines_export",
    ),
]
