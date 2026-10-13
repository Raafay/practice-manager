"""Rule 16: auto-enrolment re-declaration, every three years."""

from datetime import timedelta

from apps.core.dates import add_months

from .base import Inputs, Period, fmt, iso, rule, within

HORIZON_DAYS = 180


def reenrolment_cycle(anchor):
    """The anniversary, the re-enrolment window and the re-declaration due date."""
    anniversary = add_months(anchor, 36)
    window = (add_months(anniversary, -3), add_months(anniversary, 3))
    due = add_months(anniversary, 5) - timedelta(days=1)
    return anniversary, window, due


@rule("auto_enrolment_redeclaration", "Auto-enrolment re-declaration")
def auto_enrolment_redeclaration(i: Inputs) -> list[Period]:
    anchor = i.last_reenrolment or i.auto_enrolment_start
    if not anchor:
        return []
    periods = []
    for cycle in range(1, 6):
        anniversary, (opens, closes), due = reenrolment_cycle(add_months(anchor, 36 * (cycle - 1)))
        if not within(i.today, due, HORIZON_DAYS):
            continue
        periods.append(
            Period(
                key=iso(closes),
                label=f"Re-declaration for the re-enrolment date {fmt(anniversary)}",
                due_date=due,
                period_start=opens,
                period_end=closes,
                note="Calculated: five calendar months after the three-year anniversary, "
                "less a day. The re-enrolment window runs three months either side",
            )
        )
    return periods
