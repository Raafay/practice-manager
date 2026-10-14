from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.csvexport import csv_response
from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from . import deadlines, panel, services
from .forms import (
    ChangeDateForm,
    ClientServiceForm,
    ConfirmForm,
    DeadlineFilterForm,
    DoneForm,
    EndServiceForm,
    ReasonForm,
    ServiceForm,
)
from .models import ClientService, Deadline, Service

# ------------------------------------------------------------------ settings: the catalogue


class ServiceListView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def get(self, request):
        items = Service.objects.all()
        counts = {
            row["service"]: row["n"]
            for row in ClientService.objects.exclude(state="ended")
            .values("service")
            .annotate(n=Count("pk"))
        }
        for item in items:
            item.uses = counts.get(item.pk, 0)
        return render(request, "services/settings_services.html", {"items": items})


class ServiceEditView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def _render(self, request, form, instance, status=200):
        url = (
            reverse("services:edit", args=[instance.pk]) if instance.pk else reverse("services:add")
        )
        return render_form(
            request,
            title=f"Edit {instance.name}" if instance.pk else "New service",
            form=form,
            action=url,
            target="drawer",
            status=status,
        )

    def get(self, request, pk=None):
        instance = get_object_or_404(Service, pk=pk) if pk else Service()
        return self._render(request, ServiceForm(instance=instance), instance)

    def post(self, request, pk=None):
        instance = get_object_or_404(Service, pk=pk) if pk else Service()
        form = ServiceForm(request.POST, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        creating = instance.pk is None
        saved = form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} {'added' if creating else 'changed'} the service “{saved.name}”.",
            setting="service",
        )
        return done(request, reverse("services:list"), "Service saved.")


class ServiceMoveView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def post(self, request, pk, direction):
        if direction not in ("up", "down"):
            raise Http404
        ordered = list(Service.objects.all())
        index = next((i for i, s in enumerate(ordered) if s.pk == pk), None)
        if index is None:
            raise Http404
        swap = index - 1 if direction == "up" else index + 1
        if 0 <= swap < len(ordered):
            ordered[index], ordered[swap] = ordered[swap], ordered[index]
            for position, service in enumerate(ordered, start=1):
                if service.position != position * 10:
                    service.position = position * 10
                    service.save(update_fields=["position", "updated_at"])
            events.record(
                request.user,
                "setting.changed",
                f"{request.user} reordered the services.",
                setting="service",
            )
        return redirect("services:list")


class ServiceToggleView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def post(self, request, pk):
        service = get_object_or_404(Service, pk=pk)
        service.active = not service.active
        service.save(update_fields=["active", "updated_at"])
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} switched {service.name} "
            f"{'on' if service.active else 'off'} in the catalogue.",
            setting="service",
        )
        return redirect("services:list")


# ------------------------------------------------------------------ the Services panel


def render_panel(request, client, status=200, **extra):
    context = panel.panel_context(client, request.user)
    context.update(extra)
    return render(request, "services/_panel.html", context, status=status)


def get_client_service(client_pk, cs_pk) -> ClientService:
    return get_object_or_404(
        ClientService.objects.select_related("service", "client"), pk=cs_pk, client_id=client_pk
    )


class PanelView(StaffRequiredMixin, View):
    def get(self, request, pk):
        return render_panel(request, get_client(pk))


class SwitchOnView(StaffRequiredMixin, View):
    def _service(self, client, service_pk):
        service = get_object_or_404(Service, pk=service_pk, active=True)
        if not service.applies_to_type(client.client_type):
            raise Http404
        return service

    def _render(self, request, client, service, form, status=200):
        return render_form(
            request,
            title=f"Switch on {service.name}",
            form=form,
            action=reverse("services:switch_on", args=[client.pk, service.pk]),
            submit="Switch on",
            target="modal",
            status=status,
            intro=(
                "This client is not live yet, so the service is proposed. "
                "It starts when the client is made live."
                if form.pre_live
                else ""
            ),
        )

    def get(self, request, pk, service_pk):
        client = get_client(pk)
        service = self._service(client, service_pk)
        form = ClientServiceForm(client=client, service=service, user=request.user)
        return self._render(request, client, service, form)

    def post(self, request, pk, service_pk):
        client = get_client(pk)
        service = self._service(client, service_pk)
        form = ClientServiceForm(request.POST, client=client, service=service, user=request.user)
        if form.is_valid():
            try:
                form.save(request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return done(
                    request,
                    reverse("clients:detail", args=[client.pk]),
                    f"{service.name} switched on.",
                )
        return self._render(request, client, service, form, 422)


class ServiceSettingsView(StaffRequiredMixin, View):
    def _render(self, request, cs, form, status=200):
        return render_form(
            request,
            title=f"{cs.service.name}: settings",
            form=form,
            action=reverse("services:settings", args=[cs.client_id, cs.pk]),
            target="modal",
            status=status,
        )

    def get(self, request, pk, cs_pk):
        cs = get_client_service(pk, cs_pk)
        if not cs.is_open:
            raise Http404
        form = ClientServiceForm(
            client=cs.client, service=cs.service, user=request.user, instance=cs
        )
        return self._render(request, cs, form)

    def post(self, request, pk, cs_pk):
        cs = get_client_service(pk, cs_pk)
        if not cs.is_open:
            raise Http404
        form = ClientServiceForm(
            request.POST, client=cs.client, service=cs.service, user=request.user, instance=cs
        )
        if form.is_valid():
            try:
                form.save(request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return done(request, reverse("clients:detail", args=[cs.client_id]), "Saved.")
        return self._render(request, cs, form, 422)


class SwitchOffView(StaffRequiredMixin, View):
    def _render(self, request, cs, form, status=200):
        return render_form(
            request,
            title=f"Switch off {cs.service.name}",
            form=form,
            action=reverse("services:switch_off", args=[cs.client_id, cs.pk]),
            submit="Switch off",
            target="modal",
            danger=True,
            status=status,
            intro="Open deadlines for periods after the end date become not required.",
        )

    def get(self, request, pk, cs_pk):
        cs = get_client_service(pk, cs_pk)
        return self._render(request, cs, EndServiceForm())

    def post(self, request, pk, cs_pk):
        cs = get_client_service(pk, cs_pk)
        form = EndServiceForm(request.POST)
        if form.is_valid():
            try:
                services.end_service(
                    request.user,
                    cs,
                    form.cleaned_data["ends_on"],
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return done(
                    request,
                    reverse("clients:detail", args=[cs.client_id]),
                    f"{cs.service.name} switched off.",
                )
        return self._render(request, cs, form, 422)


class FeeView(StaffRequiredMixin, View):
    """Save the fee boxes on one row of the panel."""

    def post(self, request, pk, cs_pk):
        if not request.user.can("fees.view"):
            raise PermissionDenied
        cs = get_client_service(pk, cs_pk)
        if not cs.is_open:
            raise Http404
        raw = request.POST.get("fee_amount", "").strip().replace(",", "").lstrip("£")
        frequency = request.POST.get("fee_frequency", cs.fee_frequency)
        try:
            try:
                amount = Decimal(raw).quantize(Decimal("0.01")) if raw else None
            except InvalidOperation:
                raise ValidationError("Enter the fee as a number of pounds.") from None
            services.change_fee(request.user, cs, amount, frequency)
        except ValidationError as error:
            return render_panel(request, cs.client, status=422, fee_error=" ".join(error.messages))
        return render_panel(request, cs.client)


# ------------------------------------------------------------------ the Deadlines tab


class ClientDeadlinesView(ClientTabView):
    tab = "deadlines"
    tab_template = "services/tabs/_deadlines.html"

    def context_deadlines(self, request, client):
        today = timezone.localdate()
        rows = list(client.deadlines.select_related("client_service__service"))
        open_rows = [d for d in rows if d.is_open]
        closed = sorted((d for d in rows if not d.is_open), key=lambda d: d.due_date, reverse=True)
        for d in rows:
            d.state = d.shown_state(today)
            d.state_label, d.state_tone = d.state_label_tone
        return {
            "open_deadlines": open_rows,
            "closed_deadlines": closed,
            "has_services": client.client_services.exclude(state="ended").exists(),
        }


class DeadlineActionView(StaffRequiredMixin, View):
    """Mark done, not required, reopen, or change the date."""

    action = ""

    def deadline(self, pk, deadline_pk) -> Deadline:
        return get_object_or_404(
            Deadline.objects.select_related("client"), pk=deadline_pk, client_id=pk
        )

    def _url(self, deadline):
        return reverse("services:client_deadlines", args=[deadline.client_id])

    def _render(self, request, deadline, form, status=200):
        titles = {
            "done": "Mark done",
            "not_required": "Mark not required",
            "date": "Change due date",
            "reopen": "Reopen",
        }
        return render_form(
            request,
            title=f"{titles[self.action]}: {deadline.label}",
            form=form,
            action=reverse(
                f"services:deadline_{self.action}", args=[deadline.client_id, deadline.pk]
            ),
            submit=titles[self.action],
            target="modal",
            status=status,
            intro={
                "done": "Record when the work was finished.",
                "not_required": "Say why nothing is due for this period.",
                "date": (
                    f"The calculated date was {deadline.original_due_date:%d/%m/%Y}. It is kept, "
                    "and the deadline is shown as changed by hand."
                ),
                "reopen": "The deadline goes back to open.",
            }[self.action],
        )

    def make_form(self, deadline, data=None):
        if self.action == "done":
            return DoneForm(data)
        if self.action == "not_required":
            return ReasonForm(data)
        if self.action == "date":
            form = ChangeDateForm(data)
            if data is None:
                form.fields["due_date"].initial = deadline.due_date
            return form
        return ConfirmForm(data)

    def get(self, request, pk, deadline_pk):
        deadline = self.deadline(pk, deadline_pk)
        return self._render(request, deadline, self.make_form(deadline))

    def post(self, request, pk, deadline_pk):
        deadline = self.deadline(pk, deadline_pk)
        form = self.make_form(deadline, request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if self.action == "done":
                    deadlines.mark_done(
                        request.user, deadline, done_on=data["done_on"], note=data["note"]
                    )
                elif self.action == "not_required":
                    deadlines.mark_not_required(request.user, deadline, reason=data["reason"])
                elif self.action == "date":
                    deadlines.change_due_date(
                        request.user, deadline, data["due_date"], reason=data["reason"]
                    )
                else:
                    deadlines.reopen(request.user, deadline)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return done(request, self._url(deadline), "Deadline updated.")
        return self._render(request, deadline, form, 422)


# ------------------------------------------------------------------ Reports


class ReportsIndexView(StaffRequiredMixin, View):
    def get(self, request):
        return render(request, "services/reports_index.html")


def filtered_deadlines(form: DeadlineFilterForm):
    queryset = (
        Deadline.objects.open()
        .filter(client__archived_at__isnull=True)
        .select_related("client", "client__manager", "client_service__service")
    )
    data = form.cleaned_data if form.is_valid() else {}
    today = timezone.localdate()
    if data.get("overdue"):
        queryset = queryset.filter(due_date__lt=today)
    elif data.get("within"):
        queryset = queryset.filter(due_date__lte=today + timedelta(days=int(data["within"])))
    if data.get("service"):
        queryset = queryset.filter(client_service__service=data["service"])
    if data.get("manager"):
        queryset = queryset.filter(client__manager=data["manager"])
    if data.get("client"):
        text = data["client"].strip()
        queryset = queryset.filter(
            Q(client__name__icontains=text) | Q(client__reference__iexact=text)
        )
    return queryset.order_by("due_date", "client__name", "label")


class DeadlineReportView(StaffRequiredMixin, View):
    def get(self, request):
        form = DeadlineFilterForm(request.GET)
        queryset = filtered_deadlines(form)
        page = paginate(request, queryset, per_page=50)
        today = timezone.localdate()
        for d in page.object_list:
            d.state = d.shown_state(today)
            d.state_label, d.state_tone = d.state_label_tone
        keep = request.GET.copy()
        keep.pop("page", None)
        return render(
            request,
            "services/report_deadlines.html",
            {
                "form": form,
                "page": page,
                "keep_query": keep.urlencode(),
                "total": queryset.count(),
                "overdue_count": queryset.filter(due_date__lt=today).count(),
            },
        )


class DeadlineReportExportView(CapabilityRequiredMixin, View):
    required_rights = ("data.export",)
    require_reauth = True
    reauth_allow_get = False

    def get(self, request):
        form = DeadlineFilterForm(request.GET)
        today = timezone.localdate()
        response, writer = csv_response("deadlines.csv")
        writer.writerow(
            [
                "Client",
                "Reference",
                "Deadline",
                "Service",
                "Due date",
                "State",
                "Where the date came from",
                "Manager",
            ]
        )
        count = 0
        for d in filtered_deadlines(form):
            label, _tone = d.state_label_tone
            writer.writerow(
                [
                    d.client.name,
                    d.client.reference,
                    d.label,
                    d.rule_title,
                    d.due_date,
                    label,
                    d.source_note,
                    d.client.manager.name if d.client.manager else "",
                ]
            )
            count += 1
        events.record(
            request.user,
            "export.run",
            f"{request.user} exported {count} deadlines to CSV.",
            rows=count,
            list="deadlines",
            filters=urlencode(request.GET),
            on=today,
        )
        return response
