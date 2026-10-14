"""The income forecast. Plain functions: gather rows once, then compute month by month.

See docs/specs/09-time-fees-forecast.md sections 5 and 6. Sums use whole pence; each service's
monthly figure is rounded before adding (CORRECTIONS 22).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.dates import add_months, is_working_day, month_end
from apps.core.money import format_money, to_pounds
from apps.pipeline.models import Proposal, ProspectDetails
from apps.services.fees import monthly_equivalent
from apps.services.models import ClientService
from apps.timekeeping.models import TimeEntry

from . import fees, invoicing
from .models import FinanceSettings, Target

ZERO = Decimal("0.00")
CONTRACT_STATUSES = ("active", "paused", "onboarding")
FUTURE_MONTHS = 12
PAST_MONTHS = 6
MIN_DECIDED = 5
QUIET_DAYS = 14


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class ServiceRow:
    """One service of a client that may count towards the forecast."""

    monthly: Decimal  # recurring monthly equivalent; zero for one-off
    one_off: Decimal  # one-off amount; zero for recurring
    starts_on: date  # when it begins counting
    ends_on: date | None


@dataclass(frozen=True)
class ProspectRow:
    monthly: Decimal  # expected fee times the chance, in whole pence
    start: date


@dataclass(frozen=True)
class SetupFee:
    amount: Decimal
    start: date


@dataclass
class Snapshot:
    today: date
    services: list[ServiceRow] = field(default_factory=list)
    prospects: list[ProspectRow] = field(default_factory=list)
    setup_fees: list[SetupFee] = field(default_factory=list)


def start_or_default(value: date | None, today: date, days: int) -> date:
    return value or today + timedelta(days=days)


def gather(today: date | None = None, start_days: int | None = None) -> Snapshot:
    today = today or timezone.localdate()
    if start_days is None:
        start_days = FinanceSettings.load().default_start_days
    snap = Snapshot(today=today)
    expected = {
        d.client_id: d for d in ProspectDetails.objects.filter(client__status__in=CONTRACT_STATUSES)
    }
    rows = ClientService.objects.filter(
        client__status__in=CONTRACT_STATUSES, fee_amount__isnull=False
    ).select_related("client")
    for row in rows:
        onboarding = row.client.status == Client.Status.ONBOARDING
        if row.state == ClientService.State.PROPOSED:
            if not onboarding:
                continue
            details = expected.get(row.client_id)
            starts = row.starts_on or start_or_default(
                details.expected_start if details else None, today, start_days
            )
        elif row.state == ClientService.State.ACTIVE or row.ends_on is not None:
            # An ended service still counted in the months before it ended.
            starts = row.starts_on or date.min
        else:
            continue
        if row.fee_frequency == ClientService.Frequency.ONE_OFF:
            snap.services.append(ServiceRow(ZERO, to_pounds(row.fee_amount), starts, row.ends_on))
        else:
            monthly = monthly_equivalent(row.fee_amount, row.fee_frequency) or ZERO
            snap.services.append(ServiceRow(monthly, ZERO, starts, row.ends_on))
    for details in expected.values():
        if details.client.status == Client.Status.ONBOARDING and details.setup_fee:
            start = start_or_default(details.expected_start, today, start_days)
            snap.setup_fees.append(SetupFee(to_pounds(details.setup_fee), start))
    open_prospects = ProspectDetails.objects.filter(
        client__status=Client.Status.PROSPECT, stage__is_open=True, expected_fee__isnull=False
    ).select_related("stage")
    for details in open_prospects:
        weighted = to_pounds(Decimal(details.expected_fee) * details.stage.chance / 100)
        start = start_or_default(details.expected_start, today, start_days)
        snap.prospects.append(ProspectRow(weighted, start))
    return snap


# ---------------------------------------------------------------- one month


def first_of(day: date) -> date:
    return day.replace(day=1)


def last_of(month_start: date) -> date:
    return month_end(month_start.year, month_start.month)


def contracted(snap: Snapshot, month_start: date) -> Decimal:
    """Monthly equivalents of services that count in the month. No part-month sums."""
    last = last_of(month_start)
    return sum(
        (
            s.monthly
            for s in snap.services
            if s.monthly and s.starts_on <= last and (s.ends_on is None or s.ends_on >= last)
        ),
        ZERO,
    )


def weighted_pipeline(snap: Snapshot, month_start: date) -> Decimal:
    last = last_of(month_start)
    return sum((p.monthly for p in snap.prospects if p.start <= last), ZERO)


def one_off_income(snap: Snapshot, month_start: date) -> Decimal:
    last = last_of(month_start)
    total = sum((f.amount for f in snap.setup_fees if month_start <= f.start <= last), ZERO)
    total += sum(
        (s.one_off for s in snap.services if s.one_off and month_start <= s.starts_on <= last), ZERO
    )
    return total


def contracted_now(snap: Snapshot) -> Decimal:
    """Recurring fees contracted today."""
    today = snap.today
    return sum(
        (
            s.monthly
            for s in snap.services
            if s.monthly and s.starts_on <= today and (s.ends_on is None or s.ends_on >= today)
        ),
        ZERO,
    )


@dataclass
class MonthRow:
    month: date
    past: bool
    target: Decimal | None
    contracted: Decimal
    weighted: Decimal
    one_off: Decimal
    invoiced: Decimal | None = None

    @property
    def forecast(self) -> Decimal:
        return self.contracted + self.weighted

    @property
    def gap(self) -> Decimal | None:
        """Target minus forecast. Positive means short. None when no target is set."""
        return None if self.target is None else self.target - self.forecast

    @property
    def ahead(self) -> Decimal | None:
        return None if self.gap is None else -self.gap


def build_months(
    snap: Snapshot,
    targets: dict[date, Decimal],
    *,
    invoiced: dict[date, Decimal] | None = None,
    future: int = FUTURE_MONTHS,
    past: int = PAST_MONTHS,
) -> list[MonthRow]:
    """Last `past` months of actuals, then the next `future` months (from next month)."""
    this_month = first_of(snap.today)
    rows = [add_months(this_month, o) for o in range(-past, 0)] + [
        add_months(this_month, o) for o in range(0, future + 1)
    ]
    out = []
    for month in rows:
        is_past = month < this_month
        row = MonthRow(
            month=month,
            past=is_past,
            target=targets.get(month),
            contracted=contracted(snap, month),
            weighted=ZERO if is_past else weighted_pipeline(snap, month),
            one_off=one_off_income(snap, month),
        )
        if is_past and invoiced is not None:
            row.invoiced = invoiced.get(month)
        out.append(row)
    return out


# ---------------------------------------------------------------- feedback figures


def ceil_div(numerator: Decimal | int, denominator: Decimal | int) -> int:
    return int(math.ceil(Decimal(numerator) / Decimal(denominator)))


def average_new_client_fee(today: date | None = None) -> Decimal | None:
    """Mean monthly fee of clients made live in the last 12 months, else of all live ones."""
    today = today or timezone.localdate()
    monthly = fees.client_monthly_fees()
    recent = [
        monthly[c.pk]
        for c in Client.objects.filter(
            status__in=fees.LIVE, client_since__gt=add_months(today, -12)
        )
        if monthly.get(c.pk)
    ]
    pool = recent or [v for v in monthly.values() if v]
    if not pool:
        return None
    return to_pounds(sum(pool, ZERO) / len(pool))


def won_and_lost(today: date | None = None) -> tuple[int, int]:
    today = today or timezone.localdate()
    since = add_months(today, -12)
    won = ProspectDetails.objects.filter(won_on__gt=since, won_on__lte=today).count()
    lost = ProspectDetails.objects.filter(lost_on__gt=since, lost_on__lte=today).count()
    return won, lost


def proposals_waiting(today: date | None = None) -> tuple[Decimal, int]:
    """(monthly value waiting for an answer, how many have had no contact for 14 days)."""
    today = today or timezone.localdate()
    cutoff = timezone.make_aware(datetime.combine(today, time.min)) - timedelta(days=QUIET_DAYS)
    total, quiet = ZERO, 0
    waiting = Proposal.objects.filter(
        state__in=(Proposal.State.SENT, Proposal.State.VIEWED)
    ).select_related("client")
    for proposal in waiting:
        total += proposal.monthly_total
        details = ProspectDetails.objects.filter(client=proposal.client).first()
        last = (details.last_activity_at if details else None) or proposal.sent_at
        if last is None or last <= cutoff:
            quiet += 1
    return total, quiet


def ending_by(snap: Snapshot, month_start: date) -> Decimal:
    """Monthly fees ending after today and by the end of the month."""
    last = last_of(month_start)
    return sum(
        (
            s.monthly
            for s in snap.services
            if s.monthly and s.ends_on is not None and snap.today <= s.ends_on < last
        ),
        ZERO,
    )


def hours_last_month(today: date | None = None) -> tuple[Decimal, Decimal]:
    """(hours logged last month, hours available). Available is weekly hours by working days."""
    today = today or timezone.localdate()
    start = add_months(first_of(today), -1)
    last = last_of(start)
    minutes = (
        TimeEntry.objects.filter(date__range=(start, last)).aggregate(t=Sum("minutes"))["t"] or 0
    )
    working_days = sum(1 for i in range(last.day) if is_working_day(start + timedelta(days=i)))
    weekly = sum(
        (Decimal(u.weekly_hours) for u in User.objects.staff().filter(is_active=True)), ZERO
    )
    available = (weekly / 5 * working_days).quantize(Decimal("0.1"))
    return (Decimal(minutes) / 60).quantize(Decimal("0.1")), available


def month_label(month_start: date) -> str:
    return f"{month_start:%B %Y}"


@dataclass
class Feedback:
    month: date
    lines: list[str]
    figures: dict


def feedback(
    snap: Snapshot,
    row: MonthRow,
    *,
    target_rate: Decimal | None = None,
    today: date | None = None,
) -> Feedback:
    """The plain-English lines for one month, in the order the spec gives."""
    today = today or snap.today
    lines: list[str] = []
    label = month_label(row.month)
    gap = row.gap
    average = average_new_client_fee(today)
    won, lost = won_and_lost(today)
    decided = won + lost
    win_rate = (won * 100 // decided) if decided >= MIN_DECIDED and decided else None
    clients_needed = proposals_needed = None
    if gap is not None:
        if gap > 0:
            lines.append(f"You are {format_money(gap)} a month short of your target for {label}.")
        else:
            lines.append(f"You are {format_money(-gap)} a month ahead of your target for {label}.")
        if gap > 0 and average:
            clients_needed = ceil_div(gap, average)
            lines.append(
                f"At your average new-client fee of {format_money(average)} a month, "
                f"that is {clients_needed} more client{'s' if clients_needed != 1 else ''}."
            )
            if win_rate is not None and won:
                proposals_needed = ceil_div(clients_needed * decided, won)
                lines.append(
                    f"At your win rate of {win_rate}%, that means about {proposals_needed} "
                    f"more proposal{'s' if proposals_needed != 1 else ''}."
                )
    waiting, quiet = proposals_waiting(today)
    if waiting:
        lines.append(
            f"{format_money(waiting)} a month of proposals are waiting for an answer. "
            f"{quiet} of them have had no contact for {QUIET_DAYS} days or more."
        )
    ending = ending_by(snap, row.month)
    if ending:
        lines.append(
            f"{format_money(ending)} a month is due to end by {label} from clients leaving "
            "or reducing."
        )
    if target_rate is not None:
        below = fees.clients_below_rate(target_rate, 3, today)
        logged = TimeEntry.objects.exists()
        if logged and below:
            lines.append(
                f"{below} client{'s' if below != 1 else ''} return less than "
                f"{format_money(target_rate)} an hour."
            )
    logged_hours, available = hours_last_month(today)
    if available and logged_hours:
        line = (
            f"The team logged {logged_hours:f} hours last month against {available:f} "
            "hours available."
        )
        if logged_hours * 100 >= available * 90:
            line += " You are close to full. More work may need more people or higher fees."
        lines.append(line)
    return Feedback(
        row.month,
        lines,
        {
            "average_fee": average,
            "win_rate": win_rate,
            "won": won,
            "lost": lost,
            "clients_needed": clients_needed,
            "proposals_needed": proposals_needed,
            "waiting": waiting,
        },
    )


def month_row(snap: Snapshot, targets, month_start: date) -> MonthRow:
    """The figures for any one month, for the feedback month picker."""
    return MonthRow(
        month=month_start,
        past=month_start < first_of(snap.today),
        target=targets.get(month_start),
        contracted=contracted(snap, month_start),
        weighted=weighted_pipeline(snap, month_start),
        one_off=one_off_income(snap, month_start),
    )


def target_map() -> dict[date, Decimal]:
    return {t.month: t.amount for t in Target.objects.all()}


def load(today: date | None = None) -> tuple[Snapshot, dict[date, Decimal], list[MonthRow]]:
    snap = gather(today)
    targets = target_map()
    this_month = first_of(snap.today)
    past_months = [add_months(this_month, -n) for n in range(PAST_MONTHS, 0, -1)]
    invoiced = invoicing.invoiced_by_month(past_months) if invoicing.has_xero_data() else None
    return snap, targets, build_months(snap, targets, invoiced=invoiced)
