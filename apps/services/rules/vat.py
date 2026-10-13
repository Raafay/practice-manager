"""Rule 5: VAT returns."""

from datetime import timedelta

from apps.core.dates import add_months, month_end, vat_due

from .base import Inputs, Period, day_after, fmt, iso, rule, within

QUARTER_MONTHS = {1: (3, 6, 9, 12), 2: (1, 4, 7, 10), 3: (2, 5, 8, 11)}


def _period_ends(i: Inputs):
    """Every period end from two years back to a year ahead, oldest first."""
    frequency = i.vat_frequency
    if i.vat_scheme == "annual_accounting":
        frequency = "annual"
    first_year, last_year = i.today.year - 2, i.today.year + 1
    ends = []
    for year in range(first_year, last_year + 1):
        if frequency == "monthly":
            ends += [month_end(year, m) for m in range(1, 13)]
        elif frequency == "quarterly":
            months = QUARTER_MONTHS.get(i.vat_stagger or 0)
            if months:
                ends += [month_end(year, m) for m in months]
        elif frequency == "annual" and i.vat_year_end_month:
            ends.append(month_end(year, i.vat_year_end_month))
    return sorted(ends), frequency


@rule("vat_return", "VAT Returns")
def vat_return(i: Inputs) -> list[Period]:
    ends, frequency = _period_ends(i)
    word = {"monthly": "Month", "quarterly": "Quarter", "annual": "Year"}.get(frequency, "")
    periods = []
    for end in ends:
        if not within(i.today, end, 30):
            continue
        if frequency == "annual":
            due = add_months(end, 2)
            note = "Calculated: two months after the year ends (annual accounting scheme)"
            start = add_months(end, -12) + timedelta(days=1)
        else:
            due = vat_due(end)
            note = "Calculated: one month and seven days after the period ends"
            start = day_after(add_months(end, -1 if frequency == "monthly" else -3))
        periods.append(
            Period(
                key=iso(end),
                label=f"{word} ended {fmt(end)}",
                due_date=due,
                period_start=start,
                period_end=end,
                note=note,
            )
        )
    return periods
