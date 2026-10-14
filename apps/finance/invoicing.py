"""What Xero says was invoiced and paid, and the lists built from it.

"Invoiced" in a month is the net amount of sales invoices dated in that month whose state is
authorised or paid, less credit notes dated in that month. Owner figures: callers check rights.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.clients.models import Client
from apps.core.dates import add_months

from . import fees
from .models import FinanceSettings, XeroCreditNote, XeroInvoice

COUNTED = ("AUTHORISED", "PAID")
CHECK_TOLERANCE = Decimal("1.00")


def month_bounds(month_start: date) -> tuple[date, date]:
    return month_start, add_months(month_start, 1)


def _sum(queryset, field_name) -> Decimal:
    return queryset.aggregate(total=Sum(field_name))["total"] or Decimal("0.00")


def invoiced_in_month(month_start: date, client=None) -> Decimal:
    """Net invoiced in a month. With a client, only that client's linked Xero contacts."""
    start, end = month_bounds(month_start)
    invoices = XeroInvoice.objects.filter(status__in=COUNTED, date__gte=start, date__lt=end)
    credits = XeroCreditNote.objects.filter(status__in=COUNTED, date__gte=start, date__lt=end)
    if client is not None:
        invoices = invoices.filter(contact__client=client)
        credits = credits.filter(contact__client=client)
    return _sum(invoices, "sub_total") - _sum(credits, "sub_total")


def invoiced_by_month(month_starts: list[date]) -> dict[date, Decimal]:
    return {m: invoiced_in_month(m) for m in month_starts}


def has_xero_data() -> bool:
    return XeroInvoice.objects.exists()


# ---------------------------------------------------------------- lists


@dataclass
class OverdueGroup:
    client: Client | None
    name: str
    invoices: list = field(default_factory=list)
    today: date | None = None

    @property
    def total_due(self) -> Decimal:
        return sum((i.amount_due for i in self.invoices), Decimal("0.00"))

    @property
    def oldest_days(self) -> int:
        return max(i.days_overdue(self.today) for i in self.invoices)


def overdue_invoices(today: date | None = None):
    today = today or timezone.localdate()
    return XeroInvoice.objects.filter(
        status=XeroInvoice.Status.AUTHORISED, amount_due__gt=0, due_date__lt=today
    ).select_related("contact", "contact__client")


def overdue_groups(today: date | None = None) -> list[OverdueGroup]:
    """Unpaid invoices past their due date, grouped by client, worst first."""
    today = today or timezone.localdate()
    groups: dict[object, OverdueGroup] = {}
    for invoice in overdue_invoices(today).order_by("due_date", "id"):
        client = invoice.client
        key = ("c", client.pk) if client else ("x", invoice.contact_name)
        name = client.name if client else invoice.contact_name or "Unknown contact"
        group = groups.setdefault(key, OverdueGroup(client, name, today=today))
        group.invoices.append(invoice)
    return sorted(groups.values(), key=lambda g: (-g.oldest_days, g.name))


def overdue_total(today: date | None = None) -> Decimal:
    return _sum(overdue_invoices(today), "amount_due")


@dataclass
class NotInvoiced:
    client: Client
    monthly: Decimal


def not_invoiced(today: date | None = None, settings: FinanceSettings | None = None):
    """Live clients with a monthly fee and no invoice dated this month, after the set day."""
    today = today or timezone.localdate()
    settings = settings or FinanceSettings.load()
    if today.day <= settings.not_invoiced_after_day:
        return []
    start, end = month_bounds(today.replace(day=1))
    invoiced = set(
        XeroInvoice.objects.filter(date__gte=start, date__lt=end)
        .exclude(status__in=("VOIDED", "DELETED"))
        .exclude(contact__client__isnull=True)
        .values_list("contact__client_id", flat=True)
    )
    return [
        NotInvoiced(entry["client"], entry["monthly"])
        for entry in fees.summary().clients
        if entry["client"].pk not in invoiced
    ]


@dataclass
class CheckFee:
    client: Client
    agreed: Decimal
    invoiced: Decimal
    invoices: list

    @property
    def difference(self) -> Decimal:
        return self.invoiced - self.agreed


def check_fee(today: date | None = None) -> list[CheckFee]:
    """This month's invoiced net per client where it differs from the agreed fee by over £1."""
    today = today or timezone.localdate()
    start, end = month_bounds(today.replace(day=1))
    by_client: dict[int, list] = defaultdict(list)
    for invoice in XeroInvoice.objects.filter(
        status__in=COUNTED, date__gte=start, date__lt=end, contact__client__isnull=False
    ).select_related("contact__client"):
        by_client[invoice.contact.client_id].append(invoice)
    agreed = {e["client"].pk: e for e in fees.summary().clients}
    rows = []
    for client_id, invoices in by_client.items():
        entry = agreed.get(client_id)
        if entry is None:
            continue
        net = sum((i.sub_total for i in invoices), Decimal("0.00"))
        if abs(net - entry["monthly"]) > CHECK_TOLERANCE:
            rows.append(CheckFee(entry["client"], entry["monthly"], net, invoices))
    return sorted(rows, key=lambda r: r.client.name)


# ---------------------------------------------------------------- one client


def client_invoice_summary(client, today: date | None = None) -> dict:
    """Invoices for the client's Fees and invoices tab, with 12 month totals."""
    today = today or timezone.localdate()
    invoices = list(
        XeroInvoice.objects.filter(contact__client=client)
        .exclude(status__in=("DELETED",))
        .order_by("-date", "-id")
    )
    year_ago = add_months(today, -12)
    invoiced = sum(
        (i.sub_total for i in invoices if i.counts and i.date and i.date > year_ago),
        Decimal("0.00"),
    )
    outstanding = sum((i.amount_due for i in invoices if i.status == "AUTHORISED"), Decimal("0.00"))
    overdue = sum(
        (i.amount_due for i in invoices if i.status == "AUTHORISED" and i.days_overdue(today)),
        Decimal("0.00"),
    )
    for invoice in invoices:
        invoice.overdue_days = invoice.days_overdue(today) if invoice.status == "AUTHORISED" else 0
    return {
        "invoices": invoices,
        "invoiced_12": invoiced,
        "outstanding": outstanding,
        "overdue": overdue,
    }
