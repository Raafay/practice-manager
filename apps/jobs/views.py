from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin

from . import registry, services
from .models import JobLock, JobRun


class JobListView(CapabilityRequiredMixin, View):
    """The owner's list of background jobs, their last run and "Run now"."""

    required_rights = ("system.view",)

    def get(self, request):
        last = services.last_runs()
        requested = set(
            JobLock.objects.filter(requested_at__isnull=False).values_list("name", flat=True)
        )
        running = set(
            JobLock.objects.filter(running_since__isnull=False).values_list("name", flat=True)
        )
        rows = [
            {
                "job": job,
                "last": last.get(job.name),
                "requested": job.name in requested,
                "running": job.name in running,
            }
            for job in registry.all_jobs()
        ]
        recent = paginate(request, JobRun.objects.select_related("started_by"), per_page=25)
        labels = {job.name: job.label for job in registry.all_jobs()}
        for run in recent.object_list:
            run.label = labels.get(run.name, run.name)
        context = {"rows": rows, "page": recent, "worker_seen": services.worker_last_seen()}
        return render(request, "jobs/job_list.html", context)


class RunNowView(CapabilityRequiredMixin, View):
    required_rights = ("system.view",)

    def post(self, request, name):
        try:
            job = registry.get(name)
        except KeyError:
            raise Http404 from None
        services.request_run(request.user, name)
        messages.success(
            request, f"“{job.label}” will start within a minute, when the worker next checks."
        )
        if request.POST.get("next") == "integrations":
            return redirect("companieshouse:integrations")
        return redirect("jobs:list")
