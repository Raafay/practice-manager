"""Rules 1 to 4: dates taken from Companies House, used exactly as given."""

from datetime import timedelta

from apps.core.dates import add_months, ct_payment_due

from .base import (
    SOURCE_COMPANIES_HOUSE,
    Inputs,
    Period,
    day_after,
    fmt,
    iso,
    rule,
    within,
)

CH_NOTE = "From Companies House"


@rule("ch_accounts", "Accounts (Companies House)", always_current=True)
def ch_accounts(i: Inputs) -> list[Period]:
    end, due = i.next_accounts_made_up_to, i.next_accounts_due
    if not end or not due:
        return []
    start = day_after(i.last_accounts_made_up_to) if i.last_accounts_made_up_to else None
    start = start or i.incorporated_on
    return [
        Period(
            key=iso(end),
            label=f"Year end {fmt(end)}",
            due_date=due,
            period_start=start,
            period_end=end,
            source=SOURCE_COMPANIES_HOUSE,
            note=CH_NOTE,
        )
    ]


@rule("confirmation_statement", "Confirmation Statement", always_current=True)
def confirmation_statement(i: Inputs) -> list[Period]:
    end = i.next_statement_made_up_to
    if not end:
        return []
    if i.next_statement_due:
        due, note = i.next_statement_due, CH_NOTE
    else:
        due, note = end + timedelta(days=14), "Calculated: 14 days after the period end"
    return [
        Period(
            key=iso(end),
            label=f"Period end {fmt(end)}",
            due_date=due,
            period_start=day_after(i.last_statement_made_up_to)
            if i.last_statement_made_up_to
            else None,
            period_end=end,
            source=SOURCE_COMPANIES_HOUSE if i.next_statement_due else "calculated",
            note=note,
        )
    ]


def corporation_tax_periods(i: Inputs) -> list[tuple]:
    """Corporation tax periods as (start, end, accounts_end, is_previous).

    The current accounts period gives one period, or two when it is longer than 12
    months (the first 12 months, then the rest). The previous accounts period gives one.
    """
    found = []
    last = i.last_accounts_made_up_to
    if last:
        found.append((None, last, last, True))
    end = i.next_accounts_made_up_to
    if end:
        start = day_after(last) if last else i.incorporated_on
        if start and end > add_months(start, 12) - timedelta(days=1):
            first_end = add_months(start, 12) - timedelta(days=1)
            found.append((start, first_end, end, False))
            found.append((day_after(first_end), end, end, False))
        else:
            found.append((start, end, end, False))
    return found


@rule("ct600", "CT600 Return", always_current=True)
def ct600(i: Inputs) -> list[Period]:
    periods = []
    for start, end, accounts_end, previous in corporation_tax_periods(i):
        due = add_months(accounts_end, 12)
        if previous and due < i.today:
            continue
        periods.append(
            Period(
                key=iso(end),
                label=f"Period ended {fmt(end)}",
                due_date=due,
                period_start=start,
                period_end=end,
                note="Calculated: 12 months after the accounts period ends",
            )
        )
    return periods


@rule("ct_payment", "Corporation tax payment", reminder_only=True)
def ct_payment(i: Inputs) -> list[Period]:
    periods = []
    for start, end, _accounts_end, previous in corporation_tax_periods(i):
        due = ct_payment_due(end)
        if (previous and due < i.today) or not within(i.today, due, 60):
            continue
        periods.append(
            Period(
                key=iso(end),
                label=f"Payment for period ended {fmt(end)}",
                due_date=due,
                period_start=start,
                period_end=end,
                note="Calculated: HMRC rule CTM01800 (payment by instalments is not covered)",
            )
        )
    return periods
