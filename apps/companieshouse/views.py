from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin
from apps.jobs.models import JobRun

from . import api, services
from .forms import AddCompanyForm

SYNC_JOB = "ch_sync"


class AddSearchView(StaffRequiredMixin, View):
    """Find a company by name or number. Results load with HTMX as staff type."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        results, error = [], ""
        if len(query) >= 2:
            try:
                results = api.get_client().search(query)
            except api.CompaniesHouseError as failure:
                error = failure.public_message
        context = {"q": query, "results": results, "error": error}
        if request.htmx and not request.htmx.history_restore_request:
            return render(request, "companieshouse/_results.html", context)
        return render(request, "companieshouse/add.html", context)


class AddPreviewView(StaffRequiredMixin, View):
    """Show the company before anything is saved; confirming creates or fills in the client."""

    def _preview(self, number):
        try:
            return services.preview(number), ""
        except api.NotFound:
            raise Http404 from None
        except api.InvalidNumber:
            raise Http404 from None
        except api.CompaniesHouseError as failure:
            return None, failure.public_message

    def get(self, request, number):
        data, error = self._preview(number)
        return render(
            request,
            "companieshouse/preview.html",
            {"data": data, "error": error, "form": AddCompanyForm(), "number": number},
        )

    def post(self, request, number):
        form = AddCompanyForm(request.POST)
        if not form.is_valid():
            data, error = self._preview(number)
            return render(
                request,
                "companieshouse/preview.html",
                {"data": data, "error": error, "form": form, "number": number},
                status=422,
            )
        try:
            client, result = services.import_company(
                request.user,
                number,
                manager=form.cleaned_data["manager"],
                status=form.cleaned_data["status"],
            )
        except api.NotFound:
            raise Http404 from None
        except api.CompaniesHouseError as failure:
            messages.error(request, failure.public_message)
            return redirect("companieshouse:preview", number=number)
        people_note = f" {result.contacts_created} people added." if result.contacts_created else ""
        messages.success(request, f"{client.name} is filled in from Companies House.{people_note}")
        return redirect("companieshouse:tab", pk=client.pk)


class CompaniesHouseTabView(ClientTabView):
    tab = "companies_house"
    tab_template = "companieshouse/_tab.html"

    def context_companies_house(self, request, client):
        context = services.tab_context(client)
        context["key_present"] = api.key_present()
        return context


class SyncNowView(StaffRequiredMixin, View):
    """ "Sync now" on the tab, and "Fill in from Companies House" for a client with a number."""

    fill_in = False

    def post(self, request, pk):
        client = get_client(pk)
        url = reverse("companieshouse:tab", args=[client.pk])
        if not client.company_number:
            messages.error(request, "Add the company number on the Info tab first.")
            return done(request, reverse("clients:detail", args=[client.pk]))
        try:
            if self.fill_in:
                client, result = services.import_company(
                    request.user, client.company_number, client=client
                )
            else:
                result = services.sync_client(client, actor=request.user)
        except api.CompaniesHouseError as failure:
            messages.error(request, failure.public_message)
            return done(request, url)
        if result.first:
            text = "Filled in from Companies House."
        elif result.changes:
            text = f"Synced. {len(result.changes)} changes are on the timeline."
        else:
            text = "Synced. Nothing has changed at Companies House."
        if result.contacts_created:
            text += f" {result.contacts_created} people added."
        return done(request, url, text)


class FillInView(SyncNowView):
    fill_in = True


class IntegrationsView(CapabilityRequiredMixin, View):
    required_rights = ("integrations.manage",)

    def get(self, request):
        last = JobRun.objects.filter(name=SYNC_JOB).first()
        last_done = JobRun.objects.filter(name=SYNC_JOB, state=JobRun.State.DONE).first()
        context = {
            "key_present": api.key_present(),
            "last_run": last,
            "last_done": last_done,
            "can_run": request.user.can("system.view"),
        }
        return render(request, "companieshouse/integrations.html", context)
