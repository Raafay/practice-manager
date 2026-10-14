"""Finance pages. Every one needs finance.owner, checked here and again in the template."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.clients.models import Client
from apps.clients.views import ClientTabView
from apps.clients.views_base import get_client
from apps.core.dates import add_months
from apps.core.permissions import CapabilityRequiredMixin
from apps.jobs import services as job_services

from . import chart, chase, fees, forecast, invoicing, summary, sync, targets, xero
from .forms import FinanceSettingsForm
from .models import FinanceSettings, XeroContact

SECTIONS = [
    ("fees", "Fees", "finance:fees"),
    ("invoices", "Invoices", "finance:invoices"),
    ("targets", "Targets", "finance:targets"),
    ("forecast", "Forecast", "finance:forecast"),
    ("summary", "Summary", "finance:summary"),
    ("matching", "Xero contacts", "finance:matching"),
    ("settings", "Settings", "finance:settings"),
]


class FinanceView(CapabilityRequiredMixin, View):
    """Base: finance.owner only. `section` picks the sub-navigation tab."""

    required_rights = ("finance.owner",)
    section = ""

    def page(self, request, template, context=None, status=200):
        context = {
            "section": self.section,
            "sections": [(label, reverse(url), key) for key, label, url in SECTIONS],
            "xero": sync.status(),
            **(context or {}),
        }
        return render(request, template, context, status=status)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal(value):
    text = (value or "").strip().replace(",", "").replace("£", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"“{value}” is not an amount.") from None
    return amount


# ---------------------------------------------------------------- fees


SORTS = {
    "fee": lambda e: (-e["monthly"], e["client"].name),
    "name": lambda e: e["client"].name.lower(),
}


class FeesView(FinanceView):
    section = "fees"

    def get(self, request):
        settings = FinanceSettings.load()
        today = timezone.localdate()
        window = 12 if request.GET.get("window") == "12" else 3
        data = fees.summary()
        sort = request.GET.get("sort", "fee")
        clients = sorted(data.clients, key=SORTS.get(sort, SORTS["fee"]))
        last_month = add_months(today.replace(day=1), -1)
        return self.page(
            request,
            "finance/fees.html",
            {
                "summary": data,
                "clients": clients,
                "sort": sort if sort in SORTS else "fee",
                "this_month": today.replace(day=1),
                "last_month": last_month,
                "changes_this": fees.changes_in_month(today.replace(day=1)),
                "changes_last": fees.changes_in_month(last_month),
                "returns": fees.hourly_return(window, settings.target_hourly_rate, today),
                "window": window,
                "target_rate": settings.target_hourly_rate,
            },
        )


# ---------------------------------------------------------------- invoices and chasing


class InvoicesView(FinanceView):
    section = "invoices"

    def get(self, request):
        today = timezone.localdate()
        settings = FinanceSettings.load()
        groups = invoicing.overdue_groups(today)
        return self.page(
            request,
            "finance/invoices.html",
            {
                "not_invoiced": invoicing.not_invoiced(today, settings),
                "check_fee": invoicing.check_fee(today),
                "groups": groups,
                "overdue_total": sum((g.total_due for g in groups), Decimal("0.00")),
                "has_data": invoicing.has_xero_data(),
                "after_day": settings.not_invoiced_after_day,
                "today": today,
                "this_month": today.replace(day=1),
            },
        )


class ChaseView(FinanceView):
    section = "invoices"

    def post(self, request):
        result = chase.draft_chase_emails(request.user)
        if result["made"]:
            messages.success(
                request,
                f"{result['made']} chase message(s) drafted. They are waiting for approval "
                "on the Queued page.",
            )
        else:
            messages.info(request, "No new chase messages were needed.")
        for name, reason in result["skipped"][:5]:
            messages.warning(request, f"{name}: {reason}.")
        return redirect("finance:invoices")


# ---------------------------------------------------------------- targets


def _month_arg(value, default: date) -> date:
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except (AttributeError, ValueError):
        return default


class TargetsView(FinanceView):
    section = "targets"

    def _context(self, request, start):
        months = targets.months_from(start)
        existing = forecast.target_map()
        return {
            "rows": [(m, existing.get(m)) for m in months],
            "start": start,
            "prev": add_months(start, -12),
            "next": add_months(start, 12),
        }

    def get(self, request):
        start = _month_arg(request.GET.get("from"), timezone.localdate().replace(day=1))
        return self.page(request, "finance/targets.html", self._context(request, start))

    def post(self, request):
        start = _month_arg(request.POST.get("from"), timezone.localdate().replace(day=1))
        months = targets.months_from(start)
        action = request.POST.get("action", "save")
        try:
            if action == "yearly":
                total = _decimal(request.POST.get("yearly"))
                if total is None:
                    raise ValueError("Enter the yearly figure.")
                amounts, how = targets.spread_evenly(total), "spread a yearly figure"
            elif action == "line":
                first, last = (
                    _decimal(request.POST.get("first")),
                    _decimal(request.POST.get("last")),
                )
                if first is None or last is None:
                    raise ValueError("Enter a start and an end figure.")
                amounts, how = targets.straight_line(first, last), "straight line"
            else:
                amounts = [_decimal(request.POST.get(f"m-{m:%Y-%m}")) for m in months]
                how = "by hand"
            targets.save_targets(request.user, months, amounts, how=how)
        except ValueError as error:
            messages.error(request, str(error))
            return self.page(
                request, "finance/targets.html", self._context(request, start), status=422
            )
        messages.success(request, "Targets saved.")
        return redirect(f"{reverse('finance:targets')}?from={start:%Y-%m}")


# ---------------------------------------------------------------- forecast


class ForecastView(FinanceView):
    section = "forecast"

    def get(self, request):
        settings = FinanceSettings.load()
        snap, target_map, rows = forecast.load()
        default_month = add_months(forecast.first_of(snap.today), 1)
        month = _month_arg(request.GET.get("month"), default_month)
        picked = forecast.month_row(snap, target_map, month)
        feedback = forecast.feedback(snap, picked, target_rate=settings.target_hourly_rate)
        return self.page(
            request,
            "finance/forecast.html",
            {
                "rows": rows,
                "chart": chart.forecast_svg(rows),
                "picked": picked,
                "feedback": feedback,
                "month_choices": [r.month for r in rows if not r.past],
                "contracted_now": forecast.contracted_now(snap),
                "has_targets": bool(target_map),
                "has_xero": invoicing.has_xero_data(),
            },
        )


# ---------------------------------------------------------------- summary and settings


class SummaryView(FinanceView):
    section = "summary"

    def get(self, request):
        return self.page(request, "finance/summary.html", {"data": summary.build()})


class SettingsView(FinanceView):
    section = "settings"

    def get(self, request):
        form = FinanceSettingsForm(instance=FinanceSettings.load())
        return self.page(request, "finance/settings.html", {"form": form})

    def post(self, request):
        form = FinanceSettingsForm(request.POST, instance=FinanceSettings.load())
        if not form.is_valid():
            return self.page(request, "finance/settings.html", {"form": form}, status=422)
        form.save()
        events.record(
            request.user,
            "finance.settings_changed",
            f"{request.user.name} changed the Finance settings.",
        )
        messages.success(request, "Finance settings saved.")
        return redirect("finance:settings")


# ---------------------------------------------------------------- Xero


class MatchingView(FinanceView):
    section = "matching"

    def get(self, request):
        contacts = list(
            XeroContact.objects.exclude(match_state=XeroContact.Match.IGNORED)
            .exclude(archived=True)
            .select_related("client", "suggested_client")
        )
        clients = Client.objects.not_archived().exclude(status="lost").order_by("name")
        taken = {c.client_id for c in contacts if c.match_state == "confirmed"}
        return self.page(
            request,
            "finance/matching.html",
            {
                "contacts": contacts,
                "to_match": [c for c in contacts if c.match_state != "confirmed"],
                "matched": [c for c in contacts if c.match_state == "confirmed"],
                "ignored": XeroContact.objects.filter(
                    match_state=XeroContact.Match.IGNORED
                ).count(),
                "clients": [c for c in clients if c.pk not in taken],
            },
        )


class MatchActionView(FinanceView):
    action = ""

    def post(self, request, pk):
        contact = get_object_or_404(XeroContact, pk=pk)
        if self.action == "confirm":
            client = Client.objects.filter(pk=_int(request.POST.get("client"))).first()
            if client is None:
                messages.error(request, "Choose a client to match.")
            elif (
                XeroContact.objects.filter(client=client, match_state="confirmed")
                .exclude(pk=pk)
                .exists()
            ):
                messages.error(request, f"{client.name} is already linked to another Xero contact.")
            else:
                sync.confirm_match(request.user, contact, client)
                messages.success(request, f"“{contact.name}” matched to {client.name}.")
        elif self.action == "unmatch":
            sync.unmatch(request.user, contact)
        elif self.action == "ignore":
            sync.ignore(request.user, contact)
        else:
            raise Http404
        return redirect("finance:matching")


class XeroConnectView(FinanceView):
    """Start the Xero consent. Needs the app keys in the environment.

    Connecting an integration needs integrations.manage as well as the finance right,
    and the password again (spec 01 section 3).
    """

    required_rights = ("finance.owner", "integrations.manage")
    require_reauth = True
    reauth_allow_get = False

    def get(self, request):
        if not xero.keys_present():
            messages.error(request, "Set XERO_CLIENT_ID and XERO_CLIENT_SECRET first.")
            return redirect("companieshouse:integrations")
        state = xero.new_state()
        request.session["xero_state"] = state
        return redirect(xero.authorise_url(state))


class XeroCallbackView(FinanceView):
    def get(self, request):
        expected = request.session.pop("xero_state", "")
        if not expected or request.GET.get("state") != expected:
            raise PermissionDenied
        if request.GET.get("error") or not request.GET.get("code"):
            messages.error(request, "Xero was not connected: the consent was not given.")
            return redirect("companieshouse:integrations")
        try:
            connection = xero.XeroClient().exchange_code(request.GET["code"], request.user)
        except xero.XeroError as failure:
            messages.error(request, failure.public_message)
            return redirect("companieshouse:integrations")
        events.record(
            request.user,
            "finance.xero_connected",
            f"{request.user.name} connected Xero ({connection.tenant_name}).",
        )
        messages.success(request, f"Xero connected: {connection.tenant_name}.")
        job_services.request_run(request.user, "xero_sync")
        return redirect("companieshouse:integrations")


class XeroDisconnectView(FinanceView):
    def post(self, request):
        connection = xero.current_connection()
        if connection is not None:
            name = connection.tenant_name
            connection.delete()
            events.record(
                request.user,
                "finance.xero_disconnected",
                f"{request.user.name} disconnected Xero ({name}).",
            )
            messages.success(request, "Xero disconnected. The invoices already read are kept.")
        return redirect("companieshouse:integrations")


class XeroSyncNowView(FinanceView):
    def post(self, request):
        if xero.current_connection() is None:
            messages.error(request, "Xero is not connected.")
        else:
            job_services.request_run(request.user, "xero_sync")
            messages.success(
                request, "The Xero sync will start within a minute, when the worker next checks."
            )
        return redirect("companieshouse:integrations")


# ---------------------------------------------------------------- one client


class ClientFeesView(ClientTabView):
    """The client's Fees and invoices tab. Needs fees.view; invoices come from Xero."""

    tab = "fees"
    tab_template = "finance/tabs/_fees.html"

    def get(self, request, pk):
        if not request.user.can("fees.view"):
            raise PermissionDenied
        return super().get(request, pk)

    def context_fees(self, request, client):
        from apps.services.models import ClientService

        rows = list(
            client.client_services.exclude(state=ClientService.State.ENDED).select_related(
                "service"
            )
        )
        monthly, one_off = _totals(rows)
        today = timezone.localdate()
        contacts = list(client.xero_contacts.filter(match_state=XeroContact.Match.CONFIRMED))
        return {
            "fee_rows": rows,
            "monthly": monthly,
            "one_off": one_off,
            "xero_contacts": contacts,
            "xero_state": sync.status(),
            "can_xero": request.user.can("finance.owner"),
            **invoicing.client_invoice_summary(client, today),
        }


def _totals(rows):
    from apps.services.fees import totals

    return totals([r for r in rows if r.state == "active"])


class SendToXeroView(FinanceView):
    def post(self, request, pk):
        client = get_client(pk)
        try:
            sync.send_contact(request.user, client)
        except ValueError as error:
            messages.error(request, str(error))
        except xero.XeroError as failure:
            messages.error(request, failure.public_message)
        else:
            messages.success(request, f"{client.name} was created in Xero and linked.")
        return redirect("finance:client_fees", pk=client.pk)
