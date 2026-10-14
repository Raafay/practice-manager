"""Owner-only pieces for other pages: the Integrations section and the Overview panels."""

from __future__ import annotations

from django.utils import timezone

from . import forecast, invoicing, summary, sync, xero


def integrations_context(user) -> dict:
    """The Xero section of Settings, Integrations. Empty for anyone but the owner."""
    if not user.can("finance.owner"):
        return {}
    state = sync.status()
    from apps.jobs.models import JobRun

    return {
        "xero_panel": {
            "state": state,
            "keys": xero.keys_present(),
            "redirect_uri": xero.redirect_uri(),
            "last_log": sync_log(),
            "run": JobRun.objects.filter(name="xero_sync").first(),
        }
    }


def sync_log():
    from .models import XeroSyncLog

    return XeroSyncLog.objects.first()


def overview_context(user) -> dict:
    """Headline owner numbers for the Overview. Empty for anyone without finance.owner."""
    if not user.can("finance.owner"):
        return {}
    today = timezone.localdate()
    snap = forecast.gather(today)
    targets = forecast.target_map()
    from apps.core.dates import add_months

    next_month = add_months(forecast.first_of(today), 1)
    row = forecast.month_row(snap, targets, next_month)
    money = summary.money_section(today, snap=snap, targets=targets)
    return {
        "finance_panel": {
            "recurring": money["recurring"],
            "next_month": next_month,
            "forecast": row.forecast,
            "target": row.target,
            "gap": row.gap,
            "overdue": invoicing.overdue_total(today),
            "overdue_count": money["overdue_count"],
            "not_invoiced": len(invoicing.not_invoiced(today)),
            "lines": money["lines"],
            "xero_state": sync.status()["state"],
        }
    }
