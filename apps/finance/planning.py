"""Profit planning: targets against actuals, the gap, clients needed, scenarios, concentration.

Every figure the finance assistant quotes comes from these functions, so answers can be
repeated and checked. All amounts are pounds excluding VAT, rounded to pence. Costs are
taken as fixed: a new client adds its fee to profit until the cost run rate is changed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.core.dates import add_months
from apps.core.money import to_pounds

from . import fees, forecast
from .models import MonthlyResult, ProfitTarget

ZERO = Decimal("0.00")
CONCENTRATION_WARNING = Decimal("25")  # per cent of monthly fees from one client
RUN_RATE_MONTHS = 3


def _money(value) -> str:
    return str(to_pounds(Decimal(value)))


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    if not whole:
        return None
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"))


def this_month(today: date | None = None) -> date:
    return forecast.first_of(today or timezone.localdate())


def results(months: int = 12, today: date | None = None) -> list[MonthlyResult]:
    """Complete months of profit and loss before this month, oldest first."""
    start = add_months(this_month(today), -months)
    return list(MonthlyResult.objects.filter(month__gte=start, month__lt=this_month(today)))


def cost_run_rate(months: int = RUN_RATE_MONTHS, today: date | None = None) -> Decimal | None:
    """Average monthly costs (cost of sales plus overheads) over the last complete months."""
    rows = results(months, today)
    if not rows:
        return None
    return to_pounds(sum((r.costs for r in rows), ZERO) / len(rows))


def profit_target(month: date) -> Decimal | None:
    row = ProfitTarget.objects.filter(month=month).first()
    return row.profit if row else None


def margin_target(month: date) -> Decimal | None:
    row = ProfitTarget.objects.filter(month=month).first()
    return row.margin_percent if row else None


def fees_for_margin(costs: Decimal, margin_percent: Decimal) -> Decimal | None:
    """Monthly fees that give this net margin, costs staying fixed: costs / (1 - margin)."""
    margin = Decimal(margin_percent) / 100
    if margin >= 1:
        return None
    return to_pounds(Decimal(costs) / (1 - margin))


def position(
    target_profit: Decimal | None = None,
    today: date | None = None,
    target_margin: Decimal | None = None,
) -> dict:
    """Where profit stands now and what closing the gap takes.

    target_profit: monthly net profit wanted; defaults to this month's saved profit target.
    target_margin: net margin wanted, in per cent; defaults to this month's saved margin target.
    """
    today = today or timezone.localdate()
    snap = forecast.gather(today)
    revenue = to_pounds(forecast.contracted_now(snap))
    costs = cost_run_rate(today=today)
    profit = None if costs is None else revenue - costs
    if target_profit is None:
        target_profit = profit_target(this_month(today))
    if target_margin is None:
        target_margin = margin_target(this_month(today))
    fee_target = forecast.target_map().get(this_month(today))
    average_fee = forecast.average_new_client_fee(today)
    live_clients = sum(1 for v in fees.client_monthly_fees().values() if v)
    out = {
        "live_clients": live_clients,
        "monthly_fees_now": _money(revenue),
        "monthly_costs_run_rate": None if costs is None else _money(costs),
        "cost_run_rate_months": RUN_RATE_MONTHS,
        "monthly_profit_now": None if profit is None else _money(profit),
        "margin_percent_now": None if profit is None else str(_pct(profit, revenue)),
        "average_fee_new_clients": None if average_fee is None else _money(average_fee),
        "target_profit": None if target_profit is None else _money(target_profit),
        "gap_to_target": None,
        "clients_needed": None,
        "target_fees": None if fee_target is None else _money(fee_target),
        "clients_needed_for_fee_target": None,
        "fees_gap_to_target": None
        if fee_target is None
        else _money(max(Decimal(fee_target) - revenue, ZERO)),
        "target_margin_percent": None if target_margin is None else str(target_margin),
        "fees_needed_for_margin": None,
        "clients_needed_for_margin": None,
        "notes": [],
    }
    if fee_target is not None and average_fee and Decimal(fee_target) > revenue:
        out["clients_needed_for_fee_target"] = forecast.ceil_div(
            Decimal(fee_target) - revenue, average_fee
        )
    if target_margin is not None and costs is not None:
        needed = fees_for_margin(costs, Decimal(target_margin))
        if needed is not None:
            out["fees_needed_for_margin"] = _money(needed)
            short = needed - revenue
            if short <= 0:
                out["clients_needed_for_margin"] = 0
            elif average_fee:
                out["clients_needed_for_margin"] = forecast.ceil_div(short, average_fee)
    if costs is None:
        out["notes"].append("No profit and loss figures yet: connect Xero or type months in.")
    if target_profit is not None and profit is not None:
        gap = to_pounds(Decimal(target_profit) - profit)
        out["gap_to_target"] = _money(gap)
        if gap > 0 and average_fee:
            out["clients_needed"] = forecast.ceil_div(gap, average_fee)
        elif gap <= 0:
            out["clients_needed"] = 0
    return out


def scenario(
    new_clients: int = 0,
    fee: Decimal | None = None,
    lost_monthly_fees: Decimal = ZERO,
    extra_monthly_costs: Decimal = ZERO,
    today: date | None = None,
) -> dict:
    """Profit if `new_clients` start at `fee` a month (default: the average new client fee)."""
    if new_clients < 0 or new_clients > 500:
        raise ValueError("new_clients must be between 0 and 500.")
    today = today or timezone.localdate()
    base = position(today=today)
    if fee is None:
        fee = Decimal(base["average_fee_new_clients"] or "0")
    fee = to_pounds(Decimal(fee))
    revenue = Decimal(base["monthly_fees_now"])
    costs = Decimal(base["monthly_costs_run_rate"] or "0")
    added = to_pounds(fee * new_clients)
    new_revenue = revenue + added - to_pounds(Decimal(lost_monthly_fees))
    new_costs = costs + to_pounds(Decimal(extra_monthly_costs))
    new_profit = new_revenue - new_costs
    return {
        "new_clients": new_clients,
        "fee_each": _money(fee),
        "added_monthly_fees": _money(added),
        "lost_monthly_fees": _money(lost_monthly_fees),
        "monthly_fees_after": _money(new_revenue),
        "monthly_costs_after": _money(new_costs),
        "monthly_profit_before": base["monthly_profit_now"],
        "monthly_profit_after": _money(new_profit),
        "margin_percent_after": str(_pct(new_profit, new_revenue)),
        "target_profit": base["target_profit"],
        "costs_known": base["monthly_costs_run_rate"] is not None,
    }


def forecast_against_actual(months_back: int = 6, months_ahead: int = 6, today=None) -> list:
    """Month by month: targets, forecast fees and, for past months, actual P&L."""
    today = today or timezone.localdate()
    snap = forecast.gather(today)
    targets = forecast.target_map()
    profit_targets = {t.month: t for t in ProfitTarget.objects.all()}
    actual = {r.month: r for r in MonthlyResult.objects.all()}
    costs = cost_run_rate(today=today)
    start = this_month(today)
    rows = []
    for offset in range(-months_back, months_ahead + 1):
        month = add_months(start, offset)
        row = forecast.month_row(snap, targets, month)
        result = actual.get(month)
        forecast_profit = None if costs is None else row.forecast - costs
        goal = profit_targets.get(month)
        rows.append(
            {
                "month": month.strftime("%m/%Y"),
                "past": month < start,
                "target_fees": None if row.target is None else _money(row.target),
                "target_profit": _money(goal.profit) if goal and goal.profit is not None else None,
                "target_margin_percent": str(goal.margin_percent)
                if goal and goal.margin_percent is not None
                else None,
                "forecast_fees": _money(row.forecast),
                "forecast_profit": None if forecast_profit is None else _money(forecast_profit),
                "forecast_margin_percent": None
                if forecast_profit is None or not row.forecast
                else str(_pct(forecast_profit, row.forecast)),
                "actual_income": _money(result.income) if result else None,
                "actual_costs": _money(result.costs) if result else None,
                "actual_profit": _money(result.net_profit) if result else None,
                "actual_margin_percent": str(_pct(result.net_profit, result.income))
                if result and result.income
                else None,
            }
        )
    return rows


def margin_trend(months: int = 12, today: date | None = None) -> list[dict]:
    return [
        {
            "month": r.month.strftime("%m/%Y"),
            "income": _money(r.income),
            "net_profit": _money(r.net_profit),
            "margin_percent": None if not r.income else str(_pct(r.net_profit, r.income)),
        }
        for r in results(months, today)
    ]


def client_label(client) -> str:
    """Company names as they are; people are shown by reference only."""
    return client.name if client.is_company else f"Individual client C{client.pk:05d}"


def concentration(top: int = 10) -> dict:
    """Share of monthly fees per client, largest first, with a warning above 25%."""
    summary = fees.summary()
    total = sum((c["monthly"] for c in summary.clients), ZERO)
    rows = []
    for entry in summary.clients[:top]:
        share = _pct(entry["monthly"], total)
        rows.append(
            {
                "client": client_label(entry["client"]),
                "monthly_fees": _money(entry["monthly"]),
                "share_percent": None if share is None else str(share),
            }
        )
    warnings = [
        f"{r['client']} is {r['share_percent']}% of monthly fees."
        for r in rows
        if r["share_percent"] and Decimal(r["share_percent"]) >= CONCENTRATION_WARNING
    ]
    return {"total_monthly_fees": _money(total), "clients": rows, "warnings": warnings}


def pipeline() -> dict:
    """Open prospects with expected fee and chance, as used in the forecast."""
    snap = forecast.gather()
    waiting, quiet = forecast.proposals_waiting()
    won, lost = forecast.won_and_lost()
    return {
        "open_prospects": len(snap.prospects),
        "weighted_monthly_fees": _money(sum((p.monthly for p in snap.prospects), ZERO)),
        "proposals_waiting_monthly_value": _money(waiting),
        "proposals_quiet_14_days": quiet,
        "won_last_12_months": won,
        "lost_last_12_months": lost,
    }
