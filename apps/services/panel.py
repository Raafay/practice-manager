"""What the Services panel on the client's Info tab shows."""

from apps.clients.models import Client

from . import services
from .fees import monthly_equivalent, totals
from .models import ClientService


def panel_context(client: Client, user) -> dict:
    """Rows for every service that applies to the client, with the state of each."""
    open_rows = {
        cs.service_id: cs
        for cs in client.client_services.exclude(state=ClientService.State.ENDED).select_related(
            "service"
        )
    }
    can_fees = user.can("fees.view")
    rows = []
    for service in services.applicable_services(client):
        cs = open_rows.pop(service.pk, None)
        rows.append(_row(service, cs, can_fees))
    # Services the client still has although they no longer apply or are switched off.
    for cs in open_rows.values():
        rows.append(_row(cs.service, cs, can_fees))
    active = [r["cs"] for r in rows if r["cs"] and r["cs"].state == ClientService.State.ACTIVE]
    proposed = [r["cs"] for r in rows if r["cs"] and r["cs"].state == ClientService.State.PROPOSED]
    monthly, one_off = totals(active)
    proposed_monthly, proposed_one_off = totals(proposed)
    return {
        "client": client,
        "service_rows": rows,
        "can_fees": can_fees,
        "monthly_total": monthly,
        "one_off_total": one_off,
        "proposed_monthly": proposed_monthly,
        "proposed_one_off": proposed_one_off,
        "can_add": client.status not in (Client.Status.FORMER, Client.Status.LOST),
    }


def _row(service, cs, can_fees) -> dict:
    return {
        "service": service,
        "cs": cs,
        "has_settings": bool(services.settings_kind(service)) or service.renewal,
        "monthly": monthly_equivalent(cs.fee_amount, cs.fee_frequency) if cs and can_fees else None,
    }
