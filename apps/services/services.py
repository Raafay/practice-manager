"""Business rules for client services and fees. Views call these.

Every change writes an event; every change to a fee also writes a FeeChange row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import django.dispatch
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps import events
from apps.clients.models import Client
from apps.clients.services import client_updated, require
from apps.events.services import changes, snapshot

from . import deadlines
from .catalogue import DEFAULT_DUE_DAYS
from .models import ClientService, Deadline, FeeChange, Service

PRE_LIVE = (Client.Status.PROSPECT, Client.Status.ONBOARDING)


def applicable_services(client: Client):
    """Active catalogue services that apply to this client's type, in order."""
    return [s for s in Service.objects.filter(active=True) if s.applies_to_type(client.client_type)]


def settings_kind(service: Service) -> str:
    """Which small settings form a service opens: vat, payroll, periodic or ''."""
    rules = service.rules or []
    if "vat_return" in rules:
        return "vat"
    if "payroll_run" in rules:
        return "payroll"
    if "periodic" in rules:
        return "periodic"
    if "mtd_itsa_quarterly" in rules:
        return "mtd"
    return ""


def default_settings(service: Service) -> dict:
    if "periodic" not in (service.rules or []):
        return {}
    if service.renewal:
        return {"frequency": "annual", "due_days": 0, "renewal": True}
    return {"frequency": "monthly", "due_days": DEFAULT_DUE_DAYS.get(service.code, 14)}


def _fee_change(actor, cs, old_amount, old_frequency, *, reason="", effective_on=None):
    if cs.fee_amount == old_amount and cs.fee_frequency == old_frequency:
        return None
    return FeeChange.objects.create(
        client_service=cs,
        old_amount=old_amount,
        new_amount=cs.fee_amount,
        old_frequency=old_frequency or "",
        new_frequency=cs.fee_frequency,
        effective_on=effective_on or timezone.localdate(),
        changed_by=actor,
        reason=reason[:300],
    )


# Sent after a service is switched on for a client (client, client_service, actor).
service_added = django.dispatch.Signal()


def switch_on(
    actor,
    client: Client,
    service: Service,
    *,
    starts_on: date | None = None,
    fee_amount=None,
    fee_frequency: str = ClientService.Frequency.MONTHLY,
    settings: dict | None = None,
    notes: str = "",
) -> ClientService:
    if not service.applies_to_type(client.client_type) or not service.active:
        raise ValidationError(f"{service.name} does not apply to this client.")
    if client.status in (Client.Status.FORMER, Client.Status.LOST):
        raise ValidationError("A former or lost client cannot take new services.")
    if client.client_services.filter(service=service).exclude(state="ended").exists():
        raise ValidationError(f"{service.name} is already on for this client.")
    if fee_amount is not None:
        require(actor, "fees.view")
    elif service.default_fee is not None and actor.can("fees.view"):
        fee_amount = service.default_fee
    proposed = client.status in PRE_LIVE
    merged = {**default_settings(service), **(settings or {})}
    with transaction.atomic():
        cs = ClientService.objects.create(
            client=client,
            service=service,
            state=ClientService.State.PROPOSED if proposed else ClientService.State.ACTIVE,
            fee_amount=fee_amount,
            fee_frequency=fee_frequency,
            starts_on=None if proposed else (starts_on or timezone.localdate()),
            settings=merged,
            notes=notes,
        )
        _fee_change(actor, cs, None, "", reason="Service added")
        events.record(
            actor,
            "service.added",
            # No amounts in the summary: the timeline is shown to people who may not
            # see fees. The fee is kept in the event's data.
            f"{actor} switched on {service.name} for {client.name} "
            f"({'proposed' if proposed else 'active'}).",
            client=client,
            target=cs,
            fee_amount=fee_amount,
            fee_frequency=fee_frequency,
        )
    deadlines.generate_for_client(client, actor=actor)
    service_added.send(sender=ClientService, client=client, client_service=cs, actor=actor)
    return cs


def end_service(actor, cs: ClientService, ends_on: date, *, reason: str = "") -> ClientService:
    if not cs.is_open:
        raise ValidationError("This service has already ended.")
    client = cs.client
    with transaction.atomic():
        cs.state = ClientService.State.ENDED
        cs.ends_on = ends_on
        cs.save()
        cleared = []
        later = Deadline.objects.filter(client_service=cs, status=Deadline.Status.OPEN)
        for deadline in later:
            if (deadline.period_end or deadline.due_date) > ends_on:
                deadline.status = Deadline.Status.NOT_REQUIRED
                deadline.override_reason = f"Service ended {deadlines.fmt(ends_on)}"
                deadline.save()
                cleared.append(deadline.label)
        events.record(
            actor,
            "service.ended",
            f"{actor} ended {cs.service.name} for {client.name} on {deadlines.fmt(ends_on)}"
            + (f": {reason}" if reason else "")
            + (
                f". {len(cleared)} later deadline{'s' if len(cleared) != 1 else ''} not required."
                if cleared
                else "."
            ),
            client=client,
            target=cs,
            not_required=cleared,
            reason=reason,
        )
    return cs


def change_fee(
    actor,
    cs: ClientService,
    amount,
    frequency: str,
    *,
    reason: str = "",
    effective_on: date | None = None,
) -> ClientService:
    require(actor, "fees.view")
    if frequency not in ClientService.Frequency.values:
        raise ValidationError("Choose how often the fee is charged.")
    if amount is not None and Decimal(amount) < 0:
        raise ValidationError("A fee cannot be negative.")
    old_amount, old_frequency = cs.fee_amount, cs.fee_frequency
    if amount == old_amount and frequency == old_frequency:
        return cs
    cs.fee_amount, cs.fee_frequency = amount, frequency
    cs.save()
    _fee_change(actor, cs, old_amount, old_frequency, reason=reason, effective_on=effective_on)
    events.record(
        actor,
        "service.fee_changed",
        f"{actor} changed the fee for {cs.service.name} on {cs.client.name}.",
        client=cs.client,
        target=cs,
        old_amount=old_amount,
        new_amount=amount,
        old_frequency=old_frequency,
        new_frequency=frequency,
        reason=reason,
    )
    return cs


def update_service(
    actor, cs: ClientService, *, starts_on=None, settings=None, notes=None
) -> ClientService:
    """Change a client service's start date, settings or notes, then refresh its deadlines."""
    changed = []
    if starts_on is not None and starts_on != cs.starts_on:
        cs.starts_on = starts_on
        changed.append("start date")
    if settings is not None and settings != cs.settings:
        cs.settings = settings
        changed.append("settings")
    if notes is not None and notes != cs.notes:
        cs.notes = notes
        changed.append("notes")
    if not changed:
        return cs
    cs.save()
    events.record(
        actor,
        "service.changed",
        f"{actor} changed the {', '.join(changed)} of {cs.service.name} for {cs.client.name}.",
        client=cs.client,
        target=cs,
    )
    deadlines.generate_for_client(cs.client, actor=actor)
    return cs


def update_client_fields(actor, client: Client, values: dict, *, section: str) -> Client:
    """Set client fields from a settings form (VAT, payroll) and log what changed."""
    before = snapshot(client, list(values))
    for name, value in values.items():
        setattr(client, name, value)
    client.save(update_fields=[*values, "updated_at"])
    diff = changes(before, snapshot(client, list(values)))
    if diff:
        events.record(
            actor,
            "client.changed",
            f"{actor} changed {section.lower()} for {client.name}.",
            client=client,
            target=client,
            section=section,
            fields=diff,
        )
        client_updated.send(sender=Client, client=client, actor=actor)
    return client


def activate_proposed(client: Client, actor=None) -> list[ClientService]:
    """A client made live: proposed services become active, starting today."""
    activated = []
    today = timezone.localdate()
    for cs in client.client_services.filter(state=ClientService.State.PROPOSED):
        cs.state = ClientService.State.ACTIVE
        cs.starts_on = cs.starts_on or today
        cs.save()
        activated.append(cs)
    if activated:
        events.record(
            actor,
            "service.activated",
            f"{len(activated)} service{'s' if len(activated) != 1 else ''} became active for "
            f"{client.name}.",
            client=client,
            services=[cs.service.name for cs in activated],
        )
    return activated


def summary(client: Client) -> dict:
    """What the Services panel and the client list need: open rows and totals."""
    from .fees import totals

    rows = list(client.client_services.exclude(state="ended").select_related("service"))
    active = [r for r in rows if r.state == ClientService.State.ACTIVE]
    monthly, one_off = totals(active)
    return {"rows": rows, "monthly": monthly, "one_off": one_off}
