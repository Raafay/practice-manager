"""Rule 17: regular work from the client service's own settings.

Settings: frequency (monthly, quarterly, annual), end_month and end_day (when a
period ends; no day means the last day of the month), due_days (days after the
period end), and renewal (true for a yearly renewal, due on its date).
"""

from datetime import date, timedelta

from apps.core.dates import days_in_month

from .base import Inputs, Period, fmt, iso, rule, within

HORIZON_DAYS = 31
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
DEFAULT_DUE_DAYS = 14


def _end_in(year: int, month: int, day: int | None) -> date:
    last = days_in_month(year, month)
    return date(year, month, min(day, last) if day else last)


@rule("periodic", "Regular work")
def periodic(i: Inputs) -> list[Period]:
    s = i.settings
    step = STEP_MONTHS.get(s.get("frequency", ""))
    if not step:
        return []
    anchor_month = int(s.get("end_month") or 12)
    end_day = int(s["end_day"]) if s.get("end_day") else None
    due_days = int(s["due_days"]) if s.get("due_days") not in (None, "") else DEFAULT_DUE_DAYS
    renewal = bool(s.get("renewal"))
    periods = []
    # Months since year zero for every month that ends a period.
    first = (i.today.year - 2) * 12
    for index in range(first, first + 12 * 5):
        year, month0 = divmod(index, 12)
        month = month0 + 1
        if (month - anchor_month) % step:
            continue
        end = _end_in(year, month, end_day)
        due = end + timedelta(days=due_days)
        if not within(i.today, due, HORIZON_DAYS):
            continue
        label = f"Renewal {fmt(end)}" if renewal else f"Period ended {fmt(end)}"
        periods.append(
            Period(
                key=iso(end),
                label=label,
                due_date=due,
                period_start=None,
                period_end=end,
                note=f"Calculated: {due_days} days after the period ends"
                if due_days
                else "Calculated: on the renewal date",
            )
        )
    return periods
