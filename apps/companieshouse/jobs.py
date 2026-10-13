"""The nightly Companies House sync."""

from datetime import time

from apps.clients.models import Client
from apps.jobs.registry import Daily, register

from . import api, services
from .models import CompanySnapshot

# Stop the run if this many clients in a row cannot be reached: the service is down.
GIVE_UP_AFTER = 3


def clients_to_sync():
    return (
        Client.objects.not_archived()
        .filter(status__in=services.SYNCED_STATUSES)
        .exclude(company_number="")
        .order_by("pk")
    )


@register(
    "ch_sync",
    "Companies House sync",
    Daily(time(2, 0)),
    description="Filing dates, status, officers, owners and filings for every company client.",
)
def nightly_sync(run):
    ch = api.get_client()
    counts = {"synced": 0, "changed": 0, "failed": 0}
    in_a_row = 0
    for client in clients_to_sync():
        try:
            result = services.sync_client(client, ch=ch)
        except api.AuthFailed:
            raise
        except (api.NotFound, api.InvalidNumber) as error:
            counts["failed"] += 1
            CompanySnapshot.objects.filter(client=client).update(last_error=error.public_message)
            continue
        except api.CompaniesHouseError as error:
            counts["failed"] += 1
            in_a_row += 1
            CompanySnapshot.objects.filter(client=client).update(last_error=error.public_message)
            if in_a_row >= GIVE_UP_AFTER:
                raise
            continue
        in_a_row = 0
        counts["synced"] += 1
        if result.changes:
            counts["changed"] += 1
    if counts["failed"]:
        counts["message"] = f"{counts['failed']} could not be synced. See each client's tab."
    return counts
