"""Date helpers for UK deadlines.

The behaviour of each function is fixed by `docs/specs/03-services-and-deadlines.md`
section 5. Statutory due dates are returned as they are, even on a weekend.
Only planning dates are moved to a working day, by the caller.
"""

import calendar
import json
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

BANK_HOLIDAYS_FILE = Path(__file__).parent / "data" / "bank_holidays.json"
TAX_YEAR_END_MONTH = 4
TAX_YEAR_END_DAY = 5


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def is_month_end(d: date) -> bool:
    return d.day == days_in_month(d.year, d.month)


def month_end(year: int, month: int) -> date:
    return date(year, month, days_in_month(year, month))


def _shift_month(year: int, month: int, n: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + n
    return index // 12, index % 12 + 1


def add_months(d: date, n: int) -> date:
    """Add n months (n may be negative).

    The last day of a month maps to the last day of the target month. Any other
    day keeps its number, pulled back to the target month's last day if needed.
    """
    year, month = _shift_month(d.year, d.month, n)
    last = days_in_month(year, month)
    if is_month_end(d):
        return date(year, month, last)
    return date(year, month, min(d.day, last))


def ct_payment_due(period_end: date) -> date:
    """Corporation tax payment date for a period ending on period_end (HMRC CTM01800).

    A period ending on a month end: the first day of the tenth month after.
    Otherwise: the day after the same day number in the ninth month after, or the
    first day of the tenth month if the ninth month has no such day.
    """
    tenth_year, tenth_month = _shift_month(period_end.year, period_end.month, 10)
    if is_month_end(period_end):
        return date(tenth_year, tenth_month, 1)
    ninth_year, ninth_month = _shift_month(period_end.year, period_end.month, 9)
    if period_end.day <= days_in_month(ninth_year, ninth_month):
        return date(ninth_year, ninth_month, period_end.day) + timedelta(days=1)
    return date(tenth_year, tenth_month, 1)


def vat_due(period_end: date) -> date:
    """VAT return and payment due date: one month and seven days after the period ends."""
    if is_month_end(period_end):
        year, month = _shift_month(period_end.year, period_end.month, 2)
        return date(year, month, 7)
    return add_months(period_end, 1) + timedelta(days=7)


def tax_year_of(d: date) -> date:
    """The end date (5 April) of the tax year that d falls in."""
    end = date(d.year, TAX_YEAR_END_MONTH, TAX_YEAR_END_DAY)
    return end if d <= end else date(d.year + 1, TAX_YEAR_END_MONTH, TAX_YEAR_END_DAY)


def tax_year_start(end: date) -> date:
    """The first day (6 April) of the tax year ending on end."""
    return date(end.year - 1, TAX_YEAR_END_MONTH, TAX_YEAR_END_DAY + 1)


def tax_year_label(end: date | int) -> str:
    """Label a tax year by its end date or end year, for example "2025/26"."""
    year = end if isinstance(end, int) else end.year
    return f"{year - 1}/{year % 100:02d}"


@lru_cache(maxsize=1)
def bundled_bank_holidays() -> frozenset[date]:
    data = json.loads(BANK_HOLIDAYS_FILE.read_text())
    return frozenset(date.fromisoformat(value) for value in data["dates"])


# The merged list, kept for a while so each date check does not hit the database.
_CACHE_SECONDS = 3600
_cache: dict = {"at": None, "dates": None}


def merge_bank_holidays(bundled: frozenset[date], stored: list[str]) -> frozenset[date]:
    """Stored dates replace the bundled dates of the years they cover."""
    fetched = {date.fromisoformat(value) for value in stored}
    years = {d.year for d in fetched}
    return frozenset({d for d in bundled if d.year not in years} | fetched)


def _stored_dates() -> list[str]:
    from django.conf import settings

    if not getattr(settings, "BANK_HOLIDAYS_FROM_DATABASE", False):
        return []
    try:
        from apps.core.models import StoredBankHolidays

        row = StoredBankHolidays.objects.filter(pk=1).first()
        return list(row.dates) if row else []
    except Exception:  # noqa: BLE001 - no database yet (start-up, migrations): use the bundled list
        return []


def bank_holidays() -> frozenset[date]:
    now = time.monotonic()
    if _cache["dates"] is None or now - _cache["at"] > _CACHE_SECONDS:
        _cache["dates"] = merge_bank_holidays(bundled_bank_holidays(), _stored_dates())
        _cache["at"] = now
    return _cache["dates"]


def clear_bank_holiday_cache() -> None:
    _cache["dates"] = None


def is_working_day(d: date) -> bool:
    """Monday to Friday, less England and Wales bank holidays."""
    return d.weekday() < 5 and d not in bank_holidays()


def previous_working_day(d: date) -> date:
    """The working day on or before d."""
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def next_working_day(d: date) -> date:
    """The working day on or after d."""
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def add_working_days(d: date, n: int) -> date:
    """Move n working days from d. A negative n moves backwards. d itself is not counted."""
    step = timedelta(days=1 if n >= 0 else -1)
    remaining = abs(n)
    while remaining:
        d += step
        if is_working_day(d):
            remaining -= 1
    return d


def last_working_day_of_month(year: int, month: int) -> date:
    return previous_working_day(month_end(year, month))


def monthly_pay_date(year: int, month: int, rule_name: str, pay_day: int | None) -> date | None:
    """The pay date for a month, moved to the working day before when it is not one.

    A day the month does not have means its last day (CORRECTIONS 12).
    """
    if rule_name == "last_working_day":
        return last_working_day_of_month(year, month)
    if rule_name == "last_friday":
        d = month_end(year, month)
        while d.weekday() != 4:
            d -= timedelta(days=1)
        return previous_working_day(d)
    if rule_name == "day_of_month" and pay_day:
        return previous_working_day(date(year, month, min(pay_day, days_in_month(year, month))))
    return None


def step_pay_dates(first: date, step: int, until: date, since: date):
    """Pay dates stepping from the first one, each moved to the working day before."""
    d = first
    while d <= until:
        adjusted = previous_working_day(d)
        if adjusted >= since:
            yield adjusted
        d += timedelta(days=step)
