"""Background jobs: the Xero sync and the weekly owner summary."""

from datetime import time

from apps.jobs.registry import Daily, Every, register

from . import summary, sync


@register(
    "xero_sync",
    "Xero sync",
    Daily(time(2, 30)),
    description="Reads customers, sales invoices and credit notes changed since the last run. "
    "Reads only. Keeps the connection alive. Safe to run twice.",
)
def xero_sync(run):
    log = sync.run_sync()
    if log is None:
        return {"skipped": "not connected"}
    if log.state == "failed":
        raise RuntimeError(log.message)
    return {**log.counts, "calls": log.calls}


@register(
    "owner_summary",
    "Owner summary email",
    Every(60),
    description="Emails the owner summary to the owners on the day and from the hour set in "
    "Finance settings (Fridays at 15:00 by default). Sends once a day at most.",
)
def owner_summary(run):
    return summary.send_owner_summary()
