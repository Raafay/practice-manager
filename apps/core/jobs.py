"""The monthly bank holiday refresh. It fails quietly: the bundled list stays in use."""

import json
import logging
import urllib.request
from datetime import date, time

from django.utils import timezone

from apps.jobs.registry import Monthly, register

from . import dates
from .models import StoredBankHolidays

logger = logging.getLogger(__name__)

GOV_UK_URL = "https://www.gov.uk/bank-holidays.json"
DIVISION = "england-and-wales"


def fetch_gov_uk() -> dict:
    request = urllib.request.Request(GOV_UK_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as reply:  # noqa: S310 - fixed https address
        return json.loads(reply.read())


def parse_dates(data: dict) -> list[str]:
    """The England and Wales dates, checked. Raises ValueError if the shape is wrong."""
    events = data[DIVISION]["events"]
    found = sorted({date.fromisoformat(event["date"]).isoformat() for event in events})
    if len(found) < 8:
        raise ValueError("too few dates")
    return found


@register(
    "bank_holidays",
    "Bank holiday refresh",
    Monthly(1, time(3, 30)),
    description="England and Wales bank holidays from gov.uk. If gov.uk fails, nothing changes.",
    notify_on_failure=False,
)
def refresh_bank_holidays(run):
    try:
        found = parse_dates(fetch_gov_uk())
    except Exception as error:  # noqa: BLE001 - fail quietly, keep the list we have
        logger.warning("Bank holiday refresh skipped: %s", type(error).__name__)
        return {"message": "gov.uk could not be read, so the stored list stays in use."}
    row, _ = StoredBankHolidays.objects.get_or_create(pk=1)
    changed = sorted(set(found) ^ set(row.dates))
    row.dates = found
    row.fetched_at = timezone.now()
    row.save()
    dates.clear_bank_holiday_cache()
    return {"dates": len(found), "changed": len(changed)}
