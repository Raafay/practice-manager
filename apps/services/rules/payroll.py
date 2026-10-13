"""Rules 6 to 8 (payroll run, PAYE payment, year end) and rule 10 (CIS)."""

from datetime import date, timedelta

from apps.core.dates import (
    add_months,
    is_working_day,
    month_end,
    monthly_pay_date,
    previous_working_day,
    step_pay_dates,
    tax_year_label,
)

from .base import Inputs, Period, fmt, iso, rule, within

PAY_HORIZON_DAYS = 31
STEP_DAYS = {"weekly": 7, "fortnightly": 14, "four_weekly": 28}
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]  # fmt: skip


@rule("payroll_run", "Payroll run")
def payroll_run(i: Inputs) -> list[Period]:
    until = i.today + timedelta(days=PAY_HORIZON_DAYS)
    since = i.today - timedelta(days=400)
    periods = []
    if i.payroll_frequency == "monthly":
        for offset in range(-13, 3):
            year, month = divmod(i.today.year * 12 + i.today.month - 1 + offset, 12)
            month += 1
            pay = monthly_pay_date(year, month, i.pay_day_rule, i.pay_day)
            if pay is None or pay > until:
                continue
            periods.append(
                Period(
                    key=iso(month_end(year, month)),
                    label=f"{MONTH_NAMES[month - 1]} {year}",
                    due_date=pay,
                    period_start=date(year, month, 1),
                    period_end=month_end(year, month),
                    note="Calculated: pay day, or the working day before; RTI is due on or "
                    "before pay day",
                )
            )
    elif i.payroll_frequency in STEP_DAYS and i.first_pay_date:
        for pay in step_pay_dates(i.first_pay_date, STEP_DAYS[i.payroll_frequency], until, since):
            periods.append(
                Period(
                    key=iso(pay),
                    label=f"Pay date {fmt(pay)}",
                    due_date=pay,
                    period_end=pay,
                    note="Calculated: stepped from the first pay date; RTI is due on or "
                    "before pay day",
                )
            )
    return periods


def paye_due(tax_month_end: date) -> tuple[date, str]:
    """22nd of the month the tax month ends, and a "pay by" hint when it is not a working day."""
    due = date(tax_month_end.year, tax_month_end.month, 22)
    note = "Calculated: the 22nd of the month the tax month ends (electronic payment)"
    if not is_working_day(due):
        note += f". Pay by {fmt(previous_working_day(due))}"
    return due, note


@rule("paye_payment", "PAYE payment", reminder_only=True)
def paye_payment(i: Inputs) -> list[Period]:
    quarterly = bool(i.settings.get("paye_quarterly"))
    months = (1, 4, 7, 10) if quarterly else tuple(range(1, 13))
    periods = []
    for year in (i.today.year - 1, i.today.year, i.today.year + 1):
        for month in months:
            end = date(year, month, 5)
            due, note = paye_due(end)
            if not within(i.today, due, 60):
                continue
            span = 3 if quarterly else 1
            word = "Quarter" if quarterly else "Tax month"
            periods.append(
                Period(
                    key=iso(end),
                    label=f"{word} ended {fmt(end)}",
                    due_date=due,
                    period_start=add_months(end, -span) + timedelta(days=1),
                    period_end=end,
                    note=note + (" (quarterly payer)" if quarterly else ""),
                )
            )
    return periods


@rule("payroll_year_end", "Payroll year end")
def payroll_year_end(i: Inputs) -> list[Period]:
    periods = []
    for year in range(i.today.year - 1, i.today.year + 3):
        end = date(year, 4, 5)
        due = date(year, 5, 31)
        if not within(i.today, due, 60):
            continue
        periods.append(
            Period(
                key=iso(end),
                label=f"Tax year {tax_year_label(end)}",
                due_date=due,
                period_start=date(year - 1, 4, 6),
                period_end=end,
                note="Calculated: 31 May after the tax year (P60s to employees)",
            )
        )
    return periods


@rule("cis_return", "CIS return")
def cis_return(i: Inputs) -> list[Period]:
    periods = []
    for year in (i.today.year - 1, i.today.year, i.today.year + 1):
        for month in range(1, 13):
            end = date(year, month, 5)
            due = date(year, month, 19)
            if not within(i.today, due, 31):
                continue
            periods.append(
                Period(
                    key=iso(end),
                    label=f"Month ended {fmt(end)}",
                    due_date=due,
                    period_start=add_months(end, -1) + timedelta(days=1),
                    period_end=end,
                    note="Calculated: the 19th of the month the tax month ends",
                )
            )
    return periods
