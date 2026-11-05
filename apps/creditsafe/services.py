"""Credit checks: fetch a report for a client's company, keep the history, spot drops."""

from __future__ import annotations

import contextlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from apps import events
from apps.clients.models import Client

from . import api
from .models import CreditCheck, MonitoringState

DROP_POINTS = 10  # a fall of this many score points, or any fall in band, counts as a drop
BANDS = "ABCDE"


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def latest(client: Client) -> CreditCheck | None:
    return client.credit_checks.first()


def previous(check: CreditCheck) -> CreditCheck | None:
    return (
        CreditCheck.objects.filter(client_id=check.client_id, created_at__lt=check.created_at)
        .order_by("-created_at", "-id")
        .first()
    )


def dropped(new: CreditCheck, old: CreditCheck | None) -> bool:
    if old is None:
        return False
    if (
        new.rating in BANDS
        and old.rating in BANDS
        and BANDS.index(new.rating) > BANDS.index(old.rating)
    ):
        return True
    return new.score is not None and old.score is not None and old.score - new.score >= DROP_POINTS


def _store(client, figures, *, actor=None, source=CreditCheck.Source.CHECK, reason=""):
    check = CreditCheck.objects.create(
        client=client,
        company_number=client.company_number,
        checked_by=actor,
        source=source,
        reason=reason[:300],
        **figures,
    )
    old = previous(check)
    events.record(
        actor,
        "credit.checked",
        f"{who(actor)} checked the credit rating of {client.name}: "
        f"{check.rating or 'no band'}" + (f", score {check.score}" if check.score else "") + ".",
        client=client,
        target=check,
        source=source,
    )
    if dropped(check, old):
        from apps.accounts.models import User

        for user in User.objects.active_owners():
            events.notify(
                user,
                f"Credit rating of {client.name} fell from {old.rating or old.score} to "
                f"{check.rating or check.score}.",
                reverse("aml:tab", args=[client.pk]),
                kind="credit",
            )
    return check


@transaction.atomic
def check_client(actor, client: Client, *, transport=None) -> CreditCheck:
    """Fetch a report now. Costs one Creditsafe report. Adds the company to monitoring."""
    if not client.company_number:
        raise ValidationError("Add a company number first. Credit checks are for companies.")
    service = api.Creditsafe(transport)
    try:
        connect_id = service.find_company(client.company_number)
        figures = service.report(connect_id)
        check = _store(client, figures, actor=actor)
        # Monitoring is a convenience; the check itself worked.
        with contextlib.suppress(api.CreditsafeError):
            service.monitor(connect_id)
    except api.CreditsafeError as error:
        raise ValidationError(error.public_message) from error
    return check


def run_alerts(transport=None) -> dict:
    """Read monitoring alerts since last time and re-check only the companies named."""
    if not api.configured():
        return {"skipped": "not configured"}
    service = api.Creditsafe(transport)
    state = MonitoringState.load()
    since = state.last_event_at.isoformat() if state.last_event_at else None
    alerts = service.alerts(since)
    checked, newest = 0, state.last_event_at
    for alert in alerts:
        known = (
            CreditCheck.objects.filter(connect_id=alert["connect_id"])
            .select_related("client")
            .first()
        )
        if known is None:
            continue
        figures = service.report(alert["connect_id"])
        _store(known.client, figures, source=CreditCheck.Source.ALERT, reason=alert["description"])
        checked += 1
        from django.utils.dateparse import parse_datetime

        at = parse_datetime(alert["at"] or "")
        if at and (newest is None or at > newest):
            newest = at
    if newest != state.last_event_at:
        state.last_event_at = newest
        state.save(update_fields=["last_event_at", "updated_at"])
    return {"alerts": len(alerts), "rechecked": checked}


def recent_drops(limit: int = 10) -> list[dict]:
    """Clients whose latest rating is lower than the one before, newest first."""
    seen, rows = set(), []
    for check in CreditCheck.objects.select_related("client").order_by("-created_at", "-id")[:500]:
        if check.client_id in seen:
            continue
        seen.add(check.client_id)
        old = previous(check)
        if dropped(check, old):
            rows.append({"client": check.client, "new": check, "old": old})
        if len(rows) >= limit:
            break
    return rows
