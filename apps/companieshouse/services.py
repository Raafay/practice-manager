"""Adding a company from Companies House and keeping it up to date.

The nightly sync and "Sync now" share `sync_client`. Adding a company is a client
plus a full sync. Dates from Companies House are stored as given (DECISIONS 7).
"""

from dataclasses import dataclass, field
from datetime import date

import django.dispatch
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client

from . import api, people
from .models import CompanySnapshot

# Sent after a client is synced. Stage 4 connects the deadline job to it.
client_synced = django.dispatch.Signal()

SYNCED_STATUSES = (
    Client.Status.PROSPECT,
    Client.Status.ONBOARDING,
    Client.Status.ACTIVE,
    Client.Status.PAUSED,
)

DATE_FIELDS = {
    "last_accounts_made_up_to": "Last accounts made up to",
    "next_accounts_made_up_to": "Next accounts made up to",
    "next_accounts_due": "Next accounts due",
    "last_statement_made_up_to": "Last confirmation statement made up to",
    "next_statement_made_up_to": "Next confirmation statement made up to",
    "next_statement_due": "Next confirmation statement due",
}
OTHER_FIELDS = {
    "incorporated_on": "Incorporated on",
    "sic_codes": "SIC codes",
    "accounting_ref_day": "Accounting reference day",
    "accounting_ref_month": "Accounting reference month",
}
# Every client field the sync writes. Read-only on the Info tab once a number is set.
CH_FIELDS = ("company_status", "registered_office", *OTHER_FIELDS, *DATE_FIELDS)

CLIENT_TYPES = {"ltd": Client.Type.LTD, "plc": Client.Type.PLC, "llp": Client.Type.LLP}


def status_label(status: str) -> str:
    """ "voluntary-arrangement" to "Voluntary arrangement"."""
    text = (status or "").replace("-", " ").strip()
    return text[:1].upper() + text[1:]


def format_address(address: dict | None) -> str:
    address = address or {}
    first = " ".join(
        part for part in (address.get("premises"), address.get("address_line_1")) if part
    )
    lines = [
        first,
        address.get("address_line_2"),
        address.get("locality"),
        address.get("region"),
        address.get("postal_code"),
        address.get("country"),
    ]
    return "\n".join(line.strip() for line in lines if line and line.strip())


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def profile_fields(profile: dict) -> dict:
    """Client field values from a company profile. Missing values become empty."""
    accounts = profile.get("accounts") or {}
    ard = accounts.get("accounting_reference_date") or {}
    last_accounts = accounts.get("last_accounts") or {}
    next_accounts = accounts.get("next_accounts") or {}
    statement = profile.get("confirmation_statement") or {}
    d = people.parse_date
    return {
        "company_status": profile.get("company_status", ""),
        "incorporated_on": d(profile.get("date_of_creation")),
        "registered_office": format_address(profile.get("registered_office_address")),
        "sic_codes": ", ".join(profile.get("sic_codes") or []),
        "accounting_ref_day": _int(ard.get("day")),
        "accounting_ref_month": _int(ard.get("month")),
        "last_accounts_made_up_to": d(last_accounts.get("made_up_to")),
        "next_accounts_made_up_to": d(
            accounts.get("next_made_up_to") or next_accounts.get("period_end_on")
        ),
        "next_accounts_due": d(accounts.get("next_due") or next_accounts.get("due_on")),
        "last_statement_made_up_to": d(statement.get("last_made_up_to")),
        "next_statement_made_up_to": d(statement.get("next_made_up_to")),
        "next_statement_due": d(statement.get("next_due")),
    }


def describe_filing(item: dict) -> str:
    """A readable line for one filing, such as "Accounts with accounts type micro entity"."""
    text = (item.get("description") or item.get("type") or "Filing").replace("-", " ")
    text = text[:1].upper() + text[1:]
    made_up = people.parse_date((item.get("description_values") or {}).get("made_up_date"))
    if made_up:
        text += f", made up to {made_up:%d/%m/%Y}"
    return text


def _fmt(value) -> str:
    if value is None or value == "":
        return "blank"
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


@dataclass
class SyncResult:
    changes: list[str] = field(default_factory=list)
    full: bool = False
    first: bool = False
    contacts_created: int = 0
    links_created: int = 0
    links_updated: int = 0
    # An officer or owner was added, resigned or ceased (the AML review is prompted).
    people_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.changes) or self.first


def sync_client(
    client: Client,
    *,
    actor=None,
    ch: api.CompaniesHouseClient | None = None,
    force_full: bool = False,
    profile: dict | None = None,
    today: date | None = None,
) -> SyncResult:
    """Fetch the company and bring the client up to date. Safe to run twice.

    The profile is fetched every time. Officers, owners and filings are fetched when
    the etag changed, on Sundays, on the first sync, or when forced.
    """
    ch = ch or api.get_client()
    today = today or timezone.localdate()
    number = api.normalise_number(client.company_number)
    profile = profile if profile is not None else ch.profile(number)
    snapshot = CompanySnapshot.objects.filter(client=client).first()
    first = snapshot is None or snapshot.company_number != number
    full = (
        force_full
        or first
        or today.weekday() == 6
        or snapshot.etag != profile.get("etag", "")
        or snapshot.people_synced_at is None
    )
    if full:
        officers, owners, filings = ch.officers(number), ch.owners(number), ch.filings(number)
    else:
        officers, owners, filings = snapshot.officers, snapshot.owners, snapshot.filings

    result = SyncResult(full=full, first=first)
    now = timezone.now()
    with transaction.atomic():
        old_status = client.company_status
        new_values = profile_fields(profile)
        changed_fields = _apply_fields(client, number, new_values, now)
        if first:
            changed_names = sorted({str(f) for f in changed_fields})
            events.record(
                actor,
                "companieshouse.imported",
                f"Details filled in from Companies House for company {number}.",
                client=client,
                target=client,
                fields=changed_names,
            )
        else:
            _record_field_changes(actor, client, snapshot, profile, changed_fields, result)
            if full:
                _record_people_changes(actor, client, snapshot, officers, owners, result)
                _record_new_filings(actor, client, snapshot, filings, result)

        people_result = people.apply_people(actor, client, people.people_from(officers, owners))
        result.contacts_created = people_result.contacts_created
        result.links_created = people_result.links_created
        result.links_updated = people_result.links_updated

        CompanySnapshot.objects.update_or_create(
            client=client,
            defaults={
                "company_number": number,
                "etag": profile.get("etag", ""),
                "profile": profile,
                "officers": officers,
                "owners": owners,
                "filings": filings,
                "synced_at": now,
                "people_synced_at": now if full else snapshot.people_synced_at,
                "last_error": "",
            },
        )
    new_status = client.company_status
    if new_status and new_status != "active" and new_status != old_status:
        _notify_status(client, new_status)
    client_synced.send(sender=Client, client=client, result=result)
    return result


def _apply_fields(client: Client, number: str, values: dict, now) -> dict:
    changed = {}
    for name, value in values.items():
        if getattr(client, name) != value:
            changed[name] = (getattr(client, name), value)
            setattr(client, name, value)
    client.company_number = number
    client.last_synced_at = now
    client.save(update_fields=[*values, "company_number", "last_synced_at", "updated_at"])
    return changed


def _record_field_changes(actor, client, snapshot, profile, changed, result) -> None:
    def record(verb, summary, **data):
        result.changes.append(summary)
        events.record(actor, verb, summary, client=client, target=client, **data)

    for name, label in DATE_FIELDS.items():
        if name in changed:
            old, new = changed[name]
            record(
                "companieshouse.date_changed",
                f"Companies House: {label} changed from {_fmt(old)} to {_fmt(new)}.",
                field=name,
                old=old,
                new=new,
            )
    for name, label in OTHER_FIELDS.items():
        if name in changed:
            old, new = changed[name]
            record(
                "companieshouse.details_changed",
                f"Companies House: {label} changed from {_fmt(old)} to {_fmt(new)}.",
                field=name,
                old=old,
                new=new,
            )
    if "company_status" in changed:
        old, new = changed["company_status"]
        record(
            "companieshouse.status_changed",
            f"Companies House: status changed from {status_label(old) or 'blank'} "
            f"to {status_label(new)}.",
            old=old,
            new=new,
        )
    if "registered_office" in changed:
        record(
            "companieshouse.address_changed",
            "Companies House: registered office changed to "
            f"{changed['registered_office'][1].replace(chr(10), ', ')}.",
        )
    old_name = (snapshot.profile or {}).get("company_name", "")
    new_name = profile.get("company_name", "")
    if old_name and new_name and old_name != new_name:
        record(
            "companieshouse.name_changed",
            f"Companies House: name changed from {old_name} to {new_name}.",
            old=old_name,
            new=new_name,
        )
        # Follow the new name only if the client still had the registered one.
        if client.name.strip().lower() == old_name.strip().lower():
            client.name = new_name
            client.save(update_fields=["name", "updated_at"])


def _by_key(items: list[dict]) -> dict:
    return {people.appointment_key(item): item for item in items or []}


def _officer_label(item: dict) -> str:
    if people.is_corporate_officer(item):
        return item.get("name", "")
    parsed = people.parse_officer_name(item.get("name", ""))
    return f"{parsed['first_name']} {parsed['last_name']}".strip()


def _role_label(item: dict) -> str:
    return status_label(item.get("officer_role", "officer"))


def _record_people_changes(actor, client, snapshot, officers, owners, result) -> None:
    def record(verb, summary):
        result.people_changed = True
        result.changes.append(summary)
        events.record(actor, verb, summary, client=client, target=client)

    before = _by_key(snapshot.officers)
    for key, item in _by_key(officers).items():
        old = before.get(key)
        name, role = _officer_label(item), _role_label(item).lower()
        if item.get("resigned_on"):
            if old is None or not old.get("resigned_on"):
                when = people.parse_date(item["resigned_on"])
                record(
                    "companieshouse.officer_resigned",
                    f"Companies House: {name} resigned as {role} on {_fmt(when)}.",
                )
        elif old is None:
            when = people.parse_date(item.get("appointed_on"))
            record(
                "companieshouse.officer_appointed",
                f"Companies House: {name} appointed as {role} on {_fmt(when)}.",
            )
    before = _by_key(snapshot.owners)
    for key, item in _by_key(owners).items():
        old = before.get(key)
        name = item.get("name", "")
        if item.get("ceased_on"):
            if old is None or not old.get("ceased_on"):
                when = people.parse_date(item["ceased_on"])
                record(
                    "companieshouse.owner_ceased",
                    f"Companies House: {name} stopped being a person with significant "
                    f"control on {_fmt(when)}.",
                )
        elif old is None:
            when = people.parse_date(item.get("notified_on"))
            record(
                "companieshouse.owner_added",
                f"Companies House: {name} became a person with significant control "
                f"on {_fmt(when)}.",
            )


def _record_new_filings(actor, client, snapshot, filings, result) -> None:
    seen = {item.get("transaction_id") for item in snapshot.filings or []}
    for item in reversed(filings or []):
        if item.get("transaction_id") and item["transaction_id"] not in seen:
            when = people.parse_date(item.get("date"))
            summary = f"Companies House: new filing on {_fmt(when)}: {describe_filing(item)}."
            result.changes.append(summary)
            events.record(
                actor,
                "companieshouse.filing",
                summary,
                client=client,
                target=client,
                transaction_id=item["transaction_id"],
                filing_type=item.get("type", ""),
            )


def _notify_status(client: Client, status: str) -> None:
    """Tell the manager; with no manager, the partner; with neither, the owners."""
    from apps.accounts.models import User

    message = f"Companies House shows {client.name} as {status_label(status).lower()}."
    link = reverse("companieshouse:tab", args=[client.pk])
    for person in (client.manager, client.partner):
        if person is not None and person.is_active:
            events.notify(person, message, link)
            return
    for owner in User.objects.active_owners():
        events.notify(owner, message, link)


# ------------------------------------------------------------ adding a company


def preview(number: str, ch: api.CompaniesHouseClient | None = None) -> dict:
    """What the confirm page shows before anything is saved."""
    ch = ch or api.get_client()
    number = api.normalise_number(number)
    profile = ch.profile(number)
    officers, owners = ch.officers(number), ch.owners(number)
    return {
        "number": number,
        "profile": profile,
        "fields": profile_fields(profile),
        "status_label": status_label(profile.get("company_status", "")),
        "type_label": status_label(profile.get("type", "")),
        "officers": [_view_officer(item) for item in officers],
        "owners": [_view_owner(item) for item in owners],
        "existing": Client.objects.filter(company_number=number).first(),
    }


def import_company(
    actor,
    number: str,
    *,
    client: Client | None = None,
    manager=None,
    status: str = Client.Status.ACTIVE,
    ch: api.CompaniesHouseClient | None = None,
) -> tuple[Client, SyncResult]:
    """Create the client (or fill in an existing one) and its people from Companies House.

    A client already holding this company number is filled in, never duplicated.
    """
    ch = ch or api.get_client()
    number = api.normalise_number(number)
    profile = ch.profile(number)
    if client is None:
        client = Client.objects.filter(company_number=number).first()
    if client is None:
        client = client_services.create_client(
            actor,
            name=profile.get("company_name", number),
            client_type=CLIENT_TYPES.get(profile.get("type", ""), Client.Type.OTHER),
            manager=manager,
            status=status,
            company_number=number,
        )
    elif client.company_number != number:
        client.company_number = number
        client.save(update_fields=["company_number", "updated_at"])
    result = sync_client(client, actor=actor, ch=ch, force_full=True, profile=profile)
    return client, result


# ------------------------------------------------------------ for pages


def _view_officer(item: dict) -> dict:
    corporate = people.is_corporate_officer(item)
    month, year = people._birth(item)
    return {
        "name": _officer_label(item),
        "role": _role_label(item),
        "appointed_on": people.parse_date(item.get("appointed_on")),
        "resigned_on": people.parse_date(item.get("resigned_on")),
        "corporate": corporate,
        "officer_id": people.officer_id(item),
        "born": f"{month:02d}/{year}" if month and year else "",
        "verified_on": people._verified(item),
        "is_director": "director" in (item.get("officer_role") or "")
        or "member" in (item.get("officer_role") or ""),
    }


def _view_owner(item: dict) -> dict:
    natures = [status_label(n) for n in item.get("natures_of_control") or []]
    return {
        "name": item.get("name", ""),
        "kind": "Person" if people.is_person_owner(item) else "Company or other body",
        "person": people.is_person_owner(item),
        "natures": natures,
        "notified_on": people.parse_date(item.get("notified_on")),
        "ceased_on": people.parse_date(item.get("ceased_on")),
        "verified_on": people._verified(item),
    }


def tab_context(client: Client) -> dict:
    """The Companies House tab: the snapshot as held, with matched contacts."""
    snapshot = CompanySnapshot.objects.filter(client=client).first()
    if snapshot is None:
        return {"snapshot": None}
    links = {
        link.contact.ch_officer_id: link
        for link in client.client_contacts.select_related("contact")
        if link.contact.ch_officer_id
    }
    officers = [_view_officer(item) for item in snapshot.officers]
    for officer in officers:
        officer["link"] = links.get(officer["officer_id"])
    officers.sort(key=lambda o: (o["resigned_on"] is not None, o["name"]))
    owners = [_view_owner(item) for item in snapshot.owners]
    owners.sort(key=lambda o: (o["ceased_on"] is not None, o["name"]))
    filings = [
        {
            "date": people.parse_date(item.get("date")),
            "category": status_label(item.get("category", "")),
            "type": item.get("type", ""),
            "description": describe_filing(item),
        }
        for item in snapshot.filings[:25]
    ]
    profile = snapshot.profile
    return {
        "snapshot": snapshot,
        "profile": profile,
        "fields": profile_fields(profile),
        "status_label": status_label(profile.get("company_status", "")),
        "type_label": status_label(profile.get("type", "")),
        "officers": officers,
        "owners": owners,
        "filings": filings,
    }
