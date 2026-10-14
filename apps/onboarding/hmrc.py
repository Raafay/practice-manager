"""HMRC agent authorisations: what each service needs, expiry dates and the checklist tick."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps import events
from apps.clients.models import Client

from . import services as onboarding
from .models import AgentAuthorisation

Tax = AgentAuthorisation.Tax
State = AgentAuthorisation.State
Method = AgentAuthorisation.Method

LINK_DAYS = 21  # a digital handshake link expires 21 days after it is created
CODE_DAYS = 30  # a postal code is taken to expire 30 days after it is issued
NOTICE_DAYS = 7
WAITING = (State.REQUESTED, State.CODE_RECEIVED)

# service code -> the taxes that would do. Any one of them in the list satisfies the service.
SERVICE_TAXES = {
    "self_assessment": [Tax.SA],
    "ct600": [Tax.CT],
    "payroll": [Tax.PAYE],
    "vat": [Tax.VAT, Tax.MTD_VAT],
    "cis": [Tax.CIS],
    "mtd_income_tax": [Tax.MTD_IT],
}


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def needed(client: Client) -> list[tuple[str, list[str]]]:
    """(service name, acceptable taxes) for each open service that needs an authorisation."""
    out = []
    for cs in client.client_services.exclude(state="ended").select_related("service"):
        taxes = SERVICE_TAXES.get(cs.service.code)
        if taxes:
            out.append((cs.service.name, [t.value for t in taxes]))
    return out


def all_authorised(client: Client) -> bool:
    rows = needed(client)
    if not rows:
        return False
    authorised = set(
        client.agent_authorisations.filter(state=State.AUTHORISED).values_list("tax", flat=True)
    )
    return all(any(t in authorised for t in taxes) for _, taxes in rows)


def missing(client: Client) -> list[str]:
    authorised = set(
        client.agent_authorisations.filter(state=State.AUTHORISED).values_list("tax", flat=True)
    )
    return [name for name, taxes in needed(client) if not any(t in authorised for t in taxes)]


def sync_checklist(client: Client) -> None:
    onboarding.sync_system_item(client, "hmrc_authorisations", all_authorised(client))


def fill_dates(auth: AgentAuthorisation, today: date | None = None) -> None:
    """Work out the expiry dates the spec gives, unless someone has already set them."""
    today = today or timezone.localdate()
    if auth.method == Method.HANDSHAKE and auth.state != State.NOT_STARTED:
        auth.link_sent_on = auth.link_sent_on or today
        auth.link_expires_on = auth.link_expires_on or auth.link_sent_on + timedelta(days=LINK_DAYS)
    if auth.method == Method.POST_CODE and auth.state != State.NOT_STARTED:
        auth.requested_on = auth.requested_on or today
        auth.code_expires_on = auth.code_expires_on or auth.requested_on + timedelta(days=CODE_DAYS)
    if auth.state == State.REQUESTED:
        auth.requested_on = auth.requested_on or today
    if auth.state == State.CODE_RECEIVED:
        auth.code_received_on = auth.code_received_on or today
    if auth.state == State.AUTHORISED:
        auth.authorised_on = auth.authorised_on or today


def add(actor, client: Client, *, tax: str, method: str, contact=None) -> AgentAuthorisation:
    if tax not in Tax.values:
        raise ValidationError("Choose a tax.")
    live = client.agent_authorisations.filter(tax=tax).exclude(state=State.EXPIRED)
    if tax != Tax.OTHER and live.exists():
        raise ValidationError(f"{Tax(tax).label} already has an authorisation row.")
    auth = AgentAuthorisation.objects.create(
        client=client,
        tax=tax,
        method=method,
        contact=contact,
        state=State.AUTHORISED if method == Method.HELD else State.NOT_STARTED,
    )
    fill_dates(auth)
    auth.save()
    events.record(
        actor,
        "hmrc.added",
        f"{who(actor)} added the {Tax(tax).label} authorisation for {client.name}.",
        client=client,
        target=auth,
    )
    sync_checklist(client)
    return auth


def update(actor, auth: AgentAuthorisation, data: dict) -> AgentAuthorisation:
    old_state = auth.state
    old_dates = (auth.link_expires_on, auth.code_expires_on)
    for field in (
        "method",
        "state",
        "contact",
        "requested_on",
        "code_received_on",
        "code_expires_on",
        "link_sent_on",
        "link_expires_on",
        "authorised_on",
        "notes",
    ):
        if field in data:
            setattr(auth, field, data[field])
    if data.get("code"):
        auth.code = data["code"].strip()
    if data.get("clear_code"):
        auth.code = ""
    if auth.method == Method.HELD and auth.state == State.NOT_STARTED:
        auth.state = State.AUTHORISED
    fill_dates(auth)
    if (auth.link_expires_on, auth.code_expires_on) != old_dates:
        auth.expiry_notified_on = None
    auth.save()
    events.record(
        actor,
        "hmrc.updated",
        f"{who(actor)} updated the {auth.get_tax_display()} authorisation for "
        f"{auth.client.name}"
        + (
            f": {State(old_state).label} to {auth.get_state_display()}."
            if old_state != auth.state
            else "."
        ),
        client=auth.client,
        target=auth,
        old=old_state,
        new=auth.state,
    )
    sync_checklist(auth.client)
    return auth


def reveal_code(actor, auth: AgentAuthorisation) -> str:
    events.record(
        actor,
        "sensitive.revealed",
        f"{who(actor)} showed the HMRC code for the {auth.get_tax_display()} authorisation of "
        f"{auth.client.name}.",
        client=auth.client,
        target=auth,
        field="code",
    )
    return auth.code or ""


def expiring(today: date | None = None, days: int = NOTICE_DAYS):
    """Authorisations still waiting whose link or code expires within `days` (or already has)."""
    today = today or timezone.localdate()
    from django.db.models import Q

    cutoff = today + timedelta(days=days)
    return (
        AgentAuthorisation.objects.filter(state__in=WAITING)
        .filter(Q(link_expires_on__lte=cutoff) | Q(code_expires_on__lte=cutoff))
        .exclude(client__status__in=("former", "lost"))
        .select_related("client")
    )


def run_expiry(today: date | None = None) -> dict:
    """Notify the manager seven days before an expiry, and mark what has run out as expired."""
    today = today or timezone.localdate()
    notified = expired = 0
    for auth in expiring(today):
        date_ = auth.link_expires_on or auth.code_expires_on
        if date_ is not None and date_ < today:
            auth.state = State.EXPIRED
            auth.save(update_fields=["state", "updated_at"])
            events.record(
                None,
                "hmrc.expired",
                f"The {auth.get_tax_display()} authorisation request for {auth.client.name} "
                f"expired on {date_:%d/%m/%Y}.",
                client=auth.client,
                target=auth,
            )
            onboarding.notify_staff(
                auth.client,
                f"The HMRC {auth.get_tax_display()} request for {auth.client.name} has expired.",
                f"/clients/{auth.client_id}/hmrc/",
            )
            expired += 1
            sync_checklist(auth.client)
        elif auth.expiry_notified_on is None:
            onboarding.notify_staff(
                auth.client,
                f"The HMRC {auth.get_tax_display()} request for {auth.client.name} expires on "
                f"{date_:%d/%m/%Y}.",
                f"/clients/{auth.client_id}/hmrc/",
            )
            auth.expiry_notified_on = today
            auth.save(update_fields=["expiry_notified_on", "updated_at"])
            notified += 1
    return {"notified": notified, "expired": expired}
