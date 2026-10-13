from django.urls import path

from . import views

app_name = "jobs"

urlpatterns = [
    path("settings/jobs/", views.JobListView.as_view(), name="list"),
    path("settings/jobs/<slug:name>/run/", views.RunNowView.as_view(), name="run_now"),
]
