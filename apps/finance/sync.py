"""Read contacts, sales invoices and credit notes from Xero, and match contacts to clients.

The sync only reads. The one write is creating a contact when staff press "Send to Xero".
Safe to run twice: every row is updated by its Xero id.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.clients.models import Client

from . import xero
from .models import (
    XeroConnection,
    XeroContact,
    XeroCreditNote,
    XeroInvoice,
    XeroSyncLog,
)

_MS = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")
SUFFIXES = {"ltd", "limited", "llp", "plc", "the", "and", "co", "company", "cic"}
SUGGEST_RATIO = 0.88
# Look back a little before the last run so a change made during it is not missed.
OVERLAP = timedelta(minutes=10)


def parse_date(value) -> date | None:
    """Dates arrive as 2026-10-01T00:00:00 or /Date(milliseconds+0000)/. Parse both."""
    moment = parse_moment(value)
    return moment.date() if moment else None


def parse_moment(value) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if match := _MS.fullmatch(text):
        return datetime.fromtimestamp(int(match[1]) / 1000, tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def owners():
    return [u for u in User.objects.staff().filter(is_active=True) if u.can("finance.owner")]


# ---------------------------------------------------------------- matching


def normalise(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def suggest_client(name: str, clients: list[tuple[Client, str]]) -> Client | None:
    """The best client for a Xero contact name: same name once suffixes are dropped, else close."""
    target = normalise(name)
    if not target:
        return None
    best, best_ratio = None, 0.0
    for client, key in clients:
        if key == target:
            return client
        ratio = SequenceMatcher(None, target, key).ratio()
        if ratio > best_ratio:
            best, best_ratio = client, ratio
    return best if best_ratio >= SUGGEST_RATIO else None


def _candidate_clients() -> list[tuple[Client, str]]:
    return [
        (c, normalise(c.name)) for c in Client.objects.not_archived().exclude(status__in=("lost",))
    ]


def refresh_suggestions() -> int:
    """Suggest a client for every contact that is not matched, confirmed or ignored."""
    clients = _candidate_clients()
    taken = set(
        XeroContact.objects.filter(match_state=XeroContact.Match.CONFIRMED).values_list(
            "client_id", flat=True
        )
    )
    changed = 0
    for contact in XeroContact.objects.filter(
        match_state__in=(XeroContact.Match.NONE, XeroContact.Match.SUGGESTED)
    ):
        guess = suggest_client(contact.name, [(c, k) for c, k in clients if c.pk not in taken])
        state = XeroContact.Match.SUGGESTED if guess else XeroContact.Match.NONE
        if (
            contact.suggested_client_id != (guess.pk if guess else None)
            or contact.match_state != state
        ):
            contact.suggested_client = guess
            contact.match_state = state
            contact.save(update_fields=["suggested_client", "match_state", "updated_at"])
            changed += 1
    return changed


def confirm_match(actor, contact: XeroContact, client: Client) -> XeroContact:
    with transaction.atomic():
        contact.client = client
        contact.suggested_client = None
        contact.match_state = XeroContact.Match.CONFIRMED
        contact.save()
    events.record(
        actor,
        "finance.xero_matched",
        f"{actor.name} matched the Xero contact “{contact.name}” to {client.name}.",
        client=client,
        target=contact,
    )
    return contact


def unmatch(actor, contact: XeroContact) -> XeroContact:
    client = contact.client
    contact.client = None
    contact.suggested_client = None
    contact.match_state = XeroContact.Match.NONE
    contact.save()
    events.record(
        actor,
        "finance.xero_unmatched",
        f"{actor.name} removed the link between “{contact.name}” and "
        f"{client.name if client else 'a client'}.",
        client=client,
        target=contact,
    )
    refresh_suggestions()
    return contact


def ignore(actor, contact: XeroContact) -> XeroContact:
    contact.client = None
    contact.suggested_client = None
    contact.match_state = XeroContact.Match.IGNORED
    contact.save()
    events.record(
        actor,
        "finance.xero_ignored",
        f"{actor.name} ignored the Xero contact “{contact.name}”.",
        target=contact,
    )
    return contact


def send_contact(actor, client: Client, transport=None) -> XeroContact:
    """Create the client as a contact in Xero and link it. The one write to Xero."""
    if client.xero_contacts.filter(match_state=XeroContact.Match.CONFIRMED).exists():
        raise ValueError("This client is already linked to a Xero contact.")
    email = ""
    main = client.main_contact
    if main is not None and main.email:
        email = main.email
    created = xero.XeroClient(transport).create_contact(client.name, email)
    contact, _ = XeroContact.objects.update_or_create(
        xero_id=created["ContactID"],
        defaults={
            "name": created.get("Name", client.name),
            "email": created.get("EmailAddress", "") or "",
            "client": client,
            "suggested_client": None,
            "match_state": XeroContact.Match.CONFIRMED,
        },
    )
    events.record(
        actor,
        "finance.xero_contact_created",
        f"{actor.name} sent {client.name} to Xero as a new contact.",
        client=client,
        target=contact,
    )
    return contact


# ---------------------------------------------------------------- upserts


def upsert_contact(item: dict) -> XeroContact:
    contact, created = XeroContact.objects.get_or_create(
        xero_id=item["ContactID"], defaults={"name": item.get("Name", "")}
    )
    contact.name = item.get("Name", contact.name)
    contact.email = item.get("EmailAddress", "") or ""
    contact.archived = item.get("ContactStatus") == "ARCHIVED"
    contact.save()
    return contact


def _contact_for(item: dict) -> tuple[XeroContact | None, str]:
    info = item.get("Contact") or {}
    name = info.get("Name", "")
    if not info.get("ContactID"):
        return None, name
    contact, _ = XeroContact.objects.get_or_create(
        xero_id=info["ContactID"], defaults={"name": name}
    )
    return contact, name


def upsert_invoice(item: dict) -> XeroInvoice | None:
    if item.get("Type", "ACCREC") != "ACCREC":
        return None
    contact, name = _contact_for(item)
    values = {
        "number": item.get("InvoiceNumber", "") or "",
        "reference": (item.get("Reference", "") or "")[:300],
        "contact": contact,
        "contact_name": name,
        "date": parse_date(item.get("DateString") or item.get("Date")),
        "due_date": parse_date(item.get("DueDateString") or item.get("DueDate")),
        "status": item.get("Status", "DRAFT"),
        "sub_total": money(item.get("SubTotal")),
        "total_tax": money(item.get("TotalTax")),
        "total": money(item.get("Total")),
        "amount_due": money(item.get("AmountDue")),
        "amount_paid": money(item.get("AmountPaid")),
        "amount_credited": money(item.get("AmountCredited")),
        "currency": item.get("CurrencyCode", "GBP") or "GBP",
        "updated_utc": parse_moment(item.get("UpdatedDateUTC")),
    }
    invoice, _ = XeroInvoice.objects.update_or_create(xero_id=item["InvoiceID"], defaults=values)
    return invoice


def upsert_credit_note(item: dict) -> XeroCreditNote | None:
    if item.get("Type", "ACCRECCREDIT") != "ACCRECCREDIT":
        return None
    contact, name = _contact_for(item)
    values = {
        "number": item.get("CreditNoteNumber", "") or "",
        "contact": contact,
        "contact_name": name,
        "date": parse_date(item.get("DateString") or item.get("Date")),
        "status": item.get("Status", "DRAFT"),
        "sub_total": money(item.get("SubTotal")),
        "total_tax": money(item.get("TotalTax")),
        "total": money(item.get("Total")),
        "remaining_credit": money(item.get("RemainingCredit")),
        "updated_utc": parse_moment(item.get("UpdatedDateUTC")),
    }
    note, _ = XeroCreditNote.objects.update_or_create(xero_id=item["CreditNoteID"], defaults=values)
    return note


# ---------------------------------------------------------------- the run


def notify_owners_broken(error: str) -> None:
    today = timezone.localdate()
    for owner in owners():
        events.notify(
            owner,
            f"The Xero connection needs attention: {error}",
            reverse("companieshouse:integrations"),
            kind="xero_broken",
            key=f"xero-broken-{today.isoformat()}",
        )


def run_sync(transport=None, now=None) -> XeroSyncLog | None:
    """One sync. Returns the log row, or None when Xero is not connected."""
    connection = xero.current_connection()
    if connection is None:
        return None
    now = now or timezone.now()
    client = xero.XeroClient(transport)
    log = XeroSyncLog(started_at=now)
    since = connection.modified_since
    counts = {"contacts": 0, "invoices": 0, "credit_notes": 0}
    try:
        for item in client.contacts(since=since):
            upsert_contact(item)
            counts["contacts"] += 1
        for item in client.invoices(since=since):
            counts["invoices"] += 1 if upsert_invoice(item) else 0
        for item in client.credit_notes(since=since):
            counts["credit_notes"] += 1 if upsert_credit_note(item) else 0
        refresh_suggestions()
    except xero.XeroError as failure:
        log.state = XeroSyncLog.State.FAILED
        log.message = failure.public_message[:300]
        log.counts = counts
        log.calls = client.calls
        log.finished_at = timezone.now()
        log.save()
        broken = isinstance(failure, (xero.AuthFailed, xero.NotConnected))
        XeroConnection.objects.filter(pk=connection.pk).update(
            last_sync_at=now, last_error=log.message, broken=True if broken else connection.broken
        )
        notify_owners_broken(log.message)
        return log
    log.counts = counts
    log.calls = client.calls
    log.finished_at = timezone.now()
    log.save()
    XeroConnection.objects.filter(pk=connection.pk).update(
        last_sync_at=now,
        last_good_sync_at=now,
        modified_since=now - OVERLAP,
        broken=False,
        last_error="",
    )
    return log


def status() -> dict:
    """What the Finance pages and the Integrations page say about the connection."""
    connection = xero.current_connection()
    if connection is None:
        return {"state": "none", "connection": None}
    failing = connection.broken or (
        connection.last_sync_at
        and connection.last_good_sync_at != connection.last_sync_at
        and connection.last_error
    )
    return {
        "state": "broken" if failing else "ok",
        "connection": connection,
        "last_good": connection.last_good_sync_at,
        "error": connection.last_error,
    }
