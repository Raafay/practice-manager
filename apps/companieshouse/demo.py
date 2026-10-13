"""Made-up Companies House snapshots for the demo companies, so the tab has something
to show without a key. Everything here is invented. Safe to run twice."""

from datetime import date, timedelta

from django.utils import timezone

from apps.clients.models import Client, ClientContact
from apps.jobs.models import JobRun

from .models import CompanySnapshot

ADDRESS = {
    "premises": "1",
    "address_line_1": "Example Street",
    "locality": "Sampletown",
    "postal_code": "ZZ1 1ZZ",
    "country": "England",
}
OFFICER_ROLES = {"director": "director", "secretary": "secretary"}


def _iso(value):
    return value.isoformat() if value else None


def _profile(client: Client) -> dict:
    accounts = {
        "accounting_reference_date": {
            "day": str(client.accounting_ref_day or ""),
            "month": f"{client.accounting_ref_month or 0:02d}",
        },
        "next_made_up_to": _iso(client.next_accounts_made_up_to),
        "next_due": _iso(client.next_accounts_due),
        "overdue": False,
    }
    if client.last_accounts_made_up_to:
        accounts["last_accounts"] = {
            "made_up_to": _iso(client.last_accounts_made_up_to),
            "type": "micro-entity",
        }
    lines = client.registered_office.splitlines() or ["1 Example Street"]
    return {
        "company_name": client.name.upper(),
        "company_number": client.company_number,
        "company_status": client.company_status or "active",
        "type": client.client_type,
        "date_of_creation": _iso(client.incorporated_on),
        "registered_office_address": {
            "address_line_1": lines[0],
            "locality": lines[1] if len(lines) > 1 else "",
            "postal_code": lines[-1] if len(lines) > 2 else "",
        },
        "sic_codes": [c.strip() for c in client.sic_codes.split(",") if c.strip()],
        "accounts": accounts,
        "confirmation_statement": {
            "last_made_up_to": _iso(client.last_statement_made_up_to),
            "next_made_up_to": _iso(client.next_statement_made_up_to),
            "next_due": _iso(client.next_statement_due),
            "overdue": False,
        },
        "etag": f"demo-{client.company_number}",
    }


def _people(client: Client, index: int) -> tuple[list[dict], list[dict]]:
    officers, owners = [], []
    llp = client.client_type == Client.Type.LLP
    for n, link in enumerate(client.client_contacts.select_related("contact")):
        contact = link.contact
        roles = set(link.roles)
        month, year = 1 + (index + n) % 12, 1965 + (index * 3 + n) % 30
        if roles & {"director", "secretary", "member"}:
            officer_id = contact.ch_officer_id or f"DEMO{contact.pk:05d}"
            if not contact.ch_officer_id:
                contact.ch_officer_id = officer_id
                contact.birth_month, contact.birth_year = month, year
                contact.save(update_fields=["ch_officer_id", "birth_month", "birth_year"])
            role = (
                "llp-designated-member"
                if llp
                else ("director" if "director" in roles else "secretary")
            )
            item = {
                "name": f"{contact.last_name.upper()}, {contact.first_name}",
                "officer_role": role,
                "appointed_on": _iso(link.appointed_on or date(2020, 4, 1)),
                "date_of_birth": {
                    "month": contact.birth_month or month,
                    "year": contact.birth_year or year,
                },
                "nationality": "British",
                "address": ADDRESS,
                "links": {
                    "self": f"/company/{client.company_number}/appointments/A{contact.pk}",
                    "officer": {"appointments": f"/officers/{officer_id}/appointments"},
                },
            }
            if n % 2 == 0:
                item["identity_verification_details"] = {"identity_verified_on": "2026-02-10"}
            officers.append(item)
        if roles & {"shareholder", "psc"} or (link.is_main and n == 0):
            owners.append(
                {
                    "kind": "individual-person-with-significant-control",
                    "name": f"{contact.first_name} {contact.last_name}",
                    "name_elements": {"forename": contact.first_name, "surname": contact.last_name},
                    "natures_of_control": ["ownership-of-shares-50-to-75-percent"]
                    if link.is_main
                    else ["ownership-of-shares-25-to-50-percent"],
                    "notified_on": "2020-04-01",
                    "date_of_birth": {
                        "month": contact.birth_month or month,
                        "year": contact.birth_year or year,
                    },
                    "links": {"self": f"/company/{client.company_number}/psc/P{contact.pk}"},
                }
            )
    if index % 3 == 0:  # a director who left, so the resigned badge shows
        officers.append(
            {
                "name": "FORMER, Pat",
                "officer_role": "director",
                "appointed_on": "2016-05-01",
                "resigned_on": "2022-08-31",
                "date_of_birth": {"month": 7, "year": 1958},
                "address": ADDRESS,
                "links": {
                    "self": f"/company/{client.company_number}/appointments/F{index}",
                    "officer": {"appointments": f"/officers/DEMOF{index:04d}/appointments"},
                },
            }
        )
    if index % 4 == 0:
        officers.append(
            {
                "name": "SAMPLE SECRETARIAL SERVICES LIMITED",
                "officer_role": "corporate-secretary",
                "appointed_on": "2019-01-01",
                "address": ADDRESS,
                "links": {"self": f"/company/{client.company_number}/appointments/C{index}"},
            }
        )
    return officers, owners


def _filings(client: Client) -> list[dict]:
    items = []
    if client.last_statement_made_up_to:
        made = client.last_statement_made_up_to
        items.append(
            {
                "category": "confirmation-statement",
                "type": "CS01",
                "date": _iso(made + timedelta(days=5)),
                "description": "confirmation-statement-with-no-updates",
                "description_values": {"made_up_date": _iso(made)},
                "transaction_id": f"DEMO{client.pk}CS",
            }
        )
    if client.last_accounts_made_up_to:
        made = client.last_accounts_made_up_to
        items.append(
            {
                "category": "accounts",
                "type": "AA",
                "date": _iso(made + timedelta(days=200)),
                "description": "accounts-with-accounts-type-micro-entity",
                "description_values": {"made_up_date": _iso(made)},
                "transaction_id": f"DEMO{client.pk}AA",
            }
        )
    items.sort(key=lambda item: item["date"], reverse=True)
    return items


def seed() -> dict:
    now = timezone.now()
    made = 0
    companies = Client.objects.filter(company_number__startswith="ZZ").order_by("pk")
    for index, client in enumerate(companies):
        if CompanySnapshot.objects.filter(client=client).exists():
            continue
        officers, owners = _people(client, index)
        CompanySnapshot.objects.create(
            client=client,
            company_number=client.company_number,
            etag=f"demo-{client.company_number}",
            profile=_profile(client),
            officers=officers,
            owners=owners,
            filings=_filings(client),
            synced_at=now,
            people_synced_at=now,
        )
        Client.objects.filter(pk=client.pk).update(last_synced_at=now)
        # Filtered in Python: a JSON "contains" lookup is PostgreSQL only (DECISIONS 21).
        directors = [link.pk for link in client.client_contacts.all() if "director" in link.roles]
        ClientContact.objects.filter(pk__in=directors).update(
            source=ClientContact.Source.COMPANIES_HOUSE
        )
        made += 1
    if not JobRun.objects.exists():
        night = timezone.localtime(now).replace(hour=2, minute=0, second=0, microsecond=0)
        for days, state, counts, message in [
            (2, JobRun.State.DONE, {"synced": 14, "changed": 1, "failed": 0}, ""),
            (1, JobRun.State.FAILED, {}, "Failed: Companies House is not answering properly."),
            (0, JobRun.State.DONE, {"synced": 14, "changed": 0, "failed": 0}, ""),
        ]:
            start = night - timedelta(days=days)
            JobRun.objects.create(
                name="ch_sync",
                started_at=start,
                finished_at=start + timedelta(seconds=31),
                state=state,
                slot=start,
                counts=counts,
                message=message,
            )
    return {"snapshots": made}
