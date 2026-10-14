"""Fee totals and hourly return for the Fees page. Owner only; the views check finance.owner."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.clients.models import Client
from apps.core.dates import add_months
from apps.core.money import to_pounds
from apps.services.fees import monthly_equivalent
from apps.services.models import ClientService, FeeChange
from apps.timekeeping.models import TimeEntry

LIVE = (Client.Status.ACTIVE, Client.Status.PAUSED)


def live_fee_rows():
    """Active services of live clients that carry a recurring fee, with the monthly figure."""
    rows = (
        ClientService.objects.filter(
            state=ClientService.State.ACTIVE, client__status__in=LIVE, fee_amount__isnull=False
        )
        .exclude(fee_frequency=ClientService.Frequency.ONE_OFF)
        .select_related("client", "client__manager", "service")
    )
    for row in rows:
        row.monthly = monthly_equivalent(row.fee_amount, row.fee_frequency)
        yield row


@dataclass
class FeeSummary:
    total: Decimal
    by_service: list[tuple[str, Decimal]]
    by_manager: list[tuple[str, Decimal]]
    by_type: list[tuple[str, Decimal]]
    clients: list[dict]


def _sorted(totals: dict) -> list[tuple[str, Decimal]]:
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))


def summary() -> FeeSummary:
    total = Decimal("0.00")
    by_service, by_manager, by_type = (
        defaultdict(Decimal),
        defaultdict(Decimal),
        defaultdict(Decimal),
    )
    per_client: dict[int, dict] = {}
    for row in live_fee_rows():
        total += row.monthly
        by_service[row.service.name] += row.monthly
        manager = row.client.manager.name if row.client.manager_id else "No manager"
        by_manager[manager] += row.monthly
        by_type[row.client.get_client_type_display()] += row.monthly
        entry = per_client.setdefault(
            row.client_id, {"client": row.client, "monthly": Decimal("0.00"), "services": 0}
        )
        entry["monthly"] += row.monthly
        entry["services"] += 1
    return FeeSummary(
        total=total,
        by_service=_sorted(by_service),
        by_manager=_sorted(by_manager),
        by_type=_sorted(by_type),
        clients=sorted(per_client.values(), key=lambda e: (-e["monthly"], e["client"].name)),
    )


def client_monthly_fees() -> dict[int, Decimal]:
    return {c["client"].pk: c["monthly"] for c in summary().clients}


# ---------------------------------------------------------------- fee changes


def _recurring(amount, frequency) -> Decimal:
    if amount is None or not frequency:
        return Decimal("0.00")
    return monthly_equivalent(amount, frequency) or Decimal("0.00")


def classify_change(change: FeeChange) -> tuple[str, Decimal]:
    """(kind, monthly difference) where kind is new, increased, reduced or ended."""
    old = _recurring(change.old_amount, change.old_frequency)
    new = _recurring(change.new_amount, change.new_frequency)
    if change.client_service.state == ClientService.State.ENDED and new == 0 and old > 0:
        return "ended", -old
    if old == 0 and new > 0:
        return "new", new
    if new == 0 and old > 0:
        return "ended", -old
    if new > old:
        return "increased", new - old
    if new < old:
        return "reduced", new - old
    return "", Decimal("0.00")


def changes_in_month(month_start: date) -> dict[str, dict]:
    """Fee changes by kind for the month starting `month_start`."""
    month_end = add_months(month_start, 1)
    result = {
        k: {"count": 0, "amount": Decimal("0.00")} for k in ("new", "increased", "reduced", "ended")
    }
    rows = FeeChange.objects.filter(
        effective_on__gte=month_start, effective_on__lt=month_end
    ).select_related("client_service", "client_service__client")
    for change in rows:
        if change.client_service.client.status not in LIVE + (Client.Status.ONBOARDING,):
            continue
        kind, amount = classify_change(change)
        if kind:
            result[kind]["count"] += 1
            result[kind]["amount"] += amount
    return result


# ---------------------------------------------------------------- hourly return


@dataclass
class ReturnRow:
    client: Client
    monthly_fee: Decimal
    fees: Decimal
    minutes: int

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.minutes) / 60).quantize(Decimal("0.01"))

    @property
    def rate(self) -> Decimal | None:
        if not self.minutes:
            return None
        return to_pounds(self.fees / (Decimal(self.minutes) / 60))


def hourly_return(months: int, target_rate: Decimal, today: date | None = None) -> dict:
    """Agreed fees over the window divided by hours logged in it, lowest first.

    The window is `months` calendar months ending with this one (so far). Fees are today's agreed
    monthly fee times the months in the window (the rate to compare, not an invoiced figure).
    """
    from django.utils import timezone

    today = today or timezone.localdate()
    since = add_months(today.replace(day=1), -(months - 1))
    minutes = dict(
        TimeEntry.objects.filter(date__gte=since, date__lte=today, client__isnull=False)
        .values_list("client_id")
        .annotate(total=Sum("minutes"))
    )
    rows, no_time = [], []
    for entry in summary().clients:
        client = entry["client"]
        row = ReturnRow(
            client, entry["monthly"], entry["monthly"] * months, minutes.get(client.pk, 0)
        )
        (rows if row.minutes else no_time).append(row)
    rows.sort(key=lambda r: (r.rate, r.client.name))
    for row in rows:
        row.below = row.rate < target_rate
    return {
        "rows": rows,
        "no_time": no_time,
        "below": [r for r in rows if r.below],
        "months": months,
        "since": since,
    }


def clients_below_rate(target_rate: Decimal, months: int = 3, today: date | None = None) -> int:
    return len(hourly_return(months, target_rate, today)["below"])
