from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from apps.accounts.models import User
from apps.clients.models import Client
from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.permissions import StaffRequiredMixin
from apps.tasks.models import Task

from . import services
from .forms import TimeEntryForm
from .models import TimeEntry


def _back(request, fallback: str) -> str:
    target = request.POST.get("next") or request.META.get("HTTP_REFERER", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return fallback


def _parse_day(value: str, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TimesheetView(StaffRequiredMixin, View):
    """The weekly timesheet: client and task rows, a column for each day."""

    def get(self, request):
        today = timezone.localdate()
        start = services.week_start(_parse_day(request.GET.get("week"), today))
        person = request.user
        if request.user.can("time.edit_all") and _id(request.GET.get("user")):
            person = get_object_or_404(User.objects.staff(), pk=_id(request.GET["user"]))
        grid = services.week_grid(person, start)
        context = {
            "grid": grid,
            "person": person,
            "week": start,
            "prev_week": start - timedelta(days=7),
            "next_week": start + timedelta(days=7),
            "this_week": services.week_start(today),
            "today": today,
            "weekly_hours": person.weekly_hours,
            "can_pick_person": request.user.can("time.edit_all"),
            "people": User.objects.staff().filter(is_active=True).order_by("name"),
            "clock": services.clock_text,
            "user_param": person.pk if person.pk != request.user.pk else "",
        }
        return render(request, "timekeeping/timesheet.html", context)


class CellView(StaffRequiredMixin, View):
    """One timesheet box, saved when it changes."""

    def post(self, request):
        person = request.user
        if _id(request.POST.get("user")):
            person = get_object_or_404(User.objects.staff(), pk=_id(request.POST["user"]))
        client = Client.objects.filter(pk=_id(request.POST.get("client"))).first()
        task = Task.objects.filter(pk=_id(request.POST.get("task"))).first()
        day = _parse_day(request.POST.get("date"), None)
        if day is None or day > timezone.localdate():
            raise Http404
        text = request.POST.get("value", "").strip()
        try:
            minutes = services.parse_duration(text) if text and text not in ("0", "0:00") else None
            services.set_cell(
                request.user, person, client=client, task=task, on_date=day, minutes=minutes
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        except PermissionDenied:
            raise
        return HttpResponse(status=204, headers={"HX-Refresh": "true"})


class EntryFormView(StaffRequiredMixin, View):
    """Log time (new) or edit an entry, on its own or from a client or task."""

    entry = None

    def get_entry(self, pk):
        entry = get_object_or_404(TimeEntry.objects.select_related("client", "task"), pk=pk)
        if not services.can_edit(self.request.user, entry):
            raise PermissionDenied
        return entry

    def action(self, entry, client):
        if entry:
            return reverse("timekeeping:edit", args=[entry.pk])
        if client:
            return reverse("timekeeping:client_log", args=[client.pk])
        return reverse("timekeeping:log")

    def render(self, request, form, entry=None, client=None, status=200):
        return render_form(
            request,
            title="Edit time" if entry else "Log time",
            form=form,
            action=self.action(entry, client),
            submit="Save time",
            status=status,
            back=reverse("timekeeping:sheet"),
            extra="timekeeping/_next_field.html",
        )

    def get(self, request, pk=None, client_pk=None):
        entry = self.get_entry(pk) if pk else None
        client = get_client(client_pk) if client_pk else None
        if entry:
            form = TimeEntryForm(
                initial={
                    "client": entry.client,
                    "service": entry.service,
                    "task": entry.task,
                    "date": entry.date,
                    "duration": services.clock_text(entry.minutes),
                    "note": entry.note,
                    "billable": entry.billable,
                }
            )
        else:
            task = Task.objects.filter(pk=_id(request.GET.get("task"))).first()
            client = client or (task.client if task else None)
            client = client or Client.objects.filter(pk=_id(request.GET.get("client"))).first()
            form = TimeEntryForm(
                initial={"client": client, "task": task, "date": timezone.localdate()}
            )
        return self.render(request, form, entry, client)

    def post(self, request, pk=None, client_pk=None):
        entry = self.get_entry(pk) if pk else None
        client = get_client(client_pk) if client_pk else None
        form = TimeEntryForm(request.POST)
        if not form.is_valid():
            return self.render(request, form, entry, client, 422)
        data = form.cleaned_data
        try:
            if entry:
                services.update_entry(
                    request.user,
                    entry,
                    client=data["client"],
                    task=data["task"],
                    service=data["service"],
                    date=data["date"],
                    minutes=data["duration"],
                    note=data["note"],
                    billable=data["billable"],
                )
            else:
                services.log_time(
                    request.user,
                    minutes=data["duration"],
                    on_date=data["date"],
                    client=data["client"] or client,
                    task=data["task"],
                    service=data["service"],
                    note=data["note"],
                    billable=data["billable"],
                )
        except ValidationError as error:
            form.add_error(None, error)
            return self.render(request, form, entry, client, 422)
        return done(request, _back(request, reverse("timekeeping:sheet")), "Time saved.")


class EntryDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(TimeEntry, pk=pk)
        services.delete_entry(request.user, entry)
        messages.success(request, "Time entry deleted.")
        return redirect(_back(request, reverse("timekeeping:sheet")))


class TimerStartView(StaffRequiredMixin, View):
    def post(self, request):
        client = Client.objects.filter(pk=_id(request.POST.get("client"))).first()
        task = Task.objects.filter(pk=_id(request.POST.get("task"))).first()
        try:
            services.start_timer(request.user, client=client, task=task)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Timer started.")
        return redirect(_back(request, reverse("timekeeping:sheet")))


class TimerStopView(StaffRequiredMixin, View):
    def post(self, request):
        entry = services.stop_timer(request.user)
        if entry:
            messages.success(
                request, f"Timer stopped: {services.format_minutes(entry.minutes)} saved."
            )
        return redirect(_back(request, reverse("timekeeping:sheet")))


class ClientTimeView(ClientTabView):
    tab = "time"
    tab_template = "timekeeping/tabs/_time.html"

    def context_time(self, request, client):
        entries = list(client.time_entries.select_related("user", "task", "service")[:200])
        for entry in entries:
            entry.editable = services.can_edit(request.user, entry)
        return {
            "entries": entries,
            "totals": services.client_totals(client),
            "clock": services.format_minutes,
        }
