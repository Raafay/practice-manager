"""Rules 9 and 11 to 15: tax-year based dates."""

from datetime import date

from apps.core.dates import tax_year_label

from .base import DEFAULT_HORIZON_DAYS, Inputs, Period, iso, rule, within


def tax_year_ends(today: date) -> list[date]:
    """5 April of each year from three years back to two ahead."""
    return [date(y, 4, 5) for y in range(today.year - 3, today.year + 3)]


def tax_year_start_of(end: date) -> date:
    return date(end.year - 1, 4, 6)


def mtd_start_date(mtd_start: str) -> date | None:
    """The first day of the first tax year in Making Tax Digital, from "2026-04"."""
    if not mtd_start or mtd_start == "not_in_scope":
        return None
    try:
        year, month = mtd_start.split("-")
        return date(int(year), int(month), 6)
    except ValueError:
        return None


def in_mtd(i: Inputs, end: date) -> bool:
    start = mtd_start_date(i.mtd_start)
    return bool(start and tax_year_start_of(end) >= start)


def _year_period(end: date, due: date, label_extra: str = "", note: str = "", key=None) -> Period:
    label = f"Tax year {tax_year_label(end)}"
    return Period(
        key=key or iso(end),
        label=f"{label}: {label_extra}" if label_extra else label,
        due_date=due,
        period_start=tax_year_start_of(end),
        period_end=end,
        note=note,
    )


@rule("self_assessment", "Self Assessment return")
def self_assessment(i: Inputs) -> list[Period]:
    periods = []
    for end in tax_year_ends(i.today):
        if i.today <= end or in_mtd(i, end):
            continue  # created on 6 April, when the tax year has ended
        periods.append(
            _year_period(
                end,
                date(end.year + 1, 1, 31),
                note="Calculated: 31 January after the tax year (online return)",
            )
        )
    return periods


@rule("sa_payment", "Self Assessment payment", reminder_only=True)
def sa_payment(i: Inputs) -> list[Period]:
    periods = []
    for end in tax_year_ends(i.today):
        january = date(end.year + 1, 1, 31)
        if within(i.today, january, DEFAULT_HORIZON_DAYS):
            periods.append(
                _year_period(
                    end,
                    january,
                    "balancing payment and first payment on account",
                    "Calculated: 31 January after the tax year",
                    key=iso(january),
                )
            )
        july = date(end.year + 1, 7, 31)
        if i.payments_on_account and within(i.today, july, DEFAULT_HORIZON_DAYS):
            periods.append(
                _year_period(
                    end,
                    july,
                    "second payment on account",
                    "Calculated: 31 July after the tax year",
                    key=iso(july),
                )
            )
    return periods


QUARTERS = [(7, 5, 8, 7), (10, 5, 11, 7), (1, 5, 2, 7), (4, 5, 5, 7)]


@rule("mtd_itsa_quarterly", "MTD for Income Tax quarterly update")
def mtd_itsa_quarterly(i: Inputs) -> list[Period]:
    start = mtd_start_date(i.mtd_start)
    if not start:
        return []
    calendar_quarters = bool(i.settings.get("calendar_quarters"))
    periods = []
    for end_year in range(i.today.year - 2, i.today.year + 3):
        year_end = date(end_year, 4, 5)
        if tax_year_start_of(year_end) < start:
            continue
        for number, (q_month, q_day, due_month, due_day) in enumerate(QUARTERS, start=1):
            q_year = end_year - 1 if q_month >= 7 else end_year
            end = date(q_year, q_month, q_day)
            due = date(q_year, due_month, due_day)
            if not within(i.today, end, 30):
                continue
            label = f"Q{number} {tax_year_label(year_end)}"
            if calendar_quarters:
                label += " (calendar quarters)"
            periods.append(
                Period(
                    key=iso(end),
                    label=label,
                    due_date=due,
                    period_end=end,
                    note="Calculated: the 7th of the month after the quarter ends",
                )
            )
    return periods


@rule("mtd_itsa_final", "MTD for Income Tax final declaration")
def mtd_itsa_final(i: Inputs) -> list[Period]:
    periods = []
    for end in tax_year_ends(i.today):
        due = date(end.year + 1, 1, 31)
        if in_mtd(i, end) and within(i.today, due, DEFAULT_HORIZON_DAYS):
            periods.append(_year_period(end, due, note="Calculated: 31 January after the tax year"))
    return periods


@rule("partnership_return", "Partnership return")
def partnership_return(i: Inputs) -> list[Period]:
    periods = []
    for end in tax_year_ends(i.today):
        due = date(end.year + 1, 1, 31)
        if within(i.today, due, DEFAULT_HORIZON_DAYS):
            periods.append(_year_period(end, due, note="Calculated: 31 January after the tax year"))
    return periods


@rule("p11d", "P11D")
def p11d(i: Inputs) -> list[Period]:
    periods = []
    for end in tax_year_ends(i.today):
        forms = date(end.year, 7, 6)
        class_1a = date(end.year, 7, 22)
        if within(i.today, forms, DEFAULT_HORIZON_DAYS):
            periods.append(
                _year_period(
                    end,
                    forms,
                    "P11D forms",
                    "Calculated: 6 July after the tax year",
                    key=iso(forms),
                )
            )
        if within(i.today, class_1a, DEFAULT_HORIZON_DAYS):
            periods.append(
                _year_period(
                    end,
                    class_1a,
                    "Class 1A National Insurance",
                    "Calculated: 22 July after the tax year (reminder)",
                    key=iso(class_1a),
                )
            )
    return periods
