from django.urls import path

from . import views

app_name = "timekeeping"

urlpatterns = [
    path("time/", views.TimesheetView.as_view(), name="sheet"),
    path("time/cell/", views.CellView.as_view(), name="cell"),
    path("time/log/", views.EntryFormView.as_view(), name="log"),
    path("time/entries/<int:pk>/edit/", views.EntryFormView.as_view(), name="edit"),
    path("time/entries/<int:pk>/delete/", views.EntryDeleteView.as_view(), name="delete"),
    path("time/timer/start/", views.TimerStartView.as_view(), name="timer_start"),
    path("time/timer/stop/", views.TimerStopView.as_view(), name="timer_stop"),
    path("clients/<int:client_pk>/time/log/", views.EntryFormView.as_view(), name="client_log"),
    path("clients/<int:pk>/time/", views.ClientTimeView.as_view(), name="client_tab"),
]
