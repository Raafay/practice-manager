"""What the confirmation statement check and the client details form ask (spec 08 sections 4, 5).

Both are built from the client's own record, so the same code draws the form for the
client, the PDF copy and the staff review screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.clients.models import Client, ClientContact, Contact
from apps.core.fields import decrypt, encrypt, mask

ENC_PREFIX = "enc:"


@dataclass
class Field:
    key: str
    label: str
    input: str = "text"  # text, textarea, date, secret
    current: str = ""  # shown to the client and staff; masked for secrets
    # Where an applied answer goes: ("client", attr) or ("contact", contact_pk, attr) or None
    target: tuple | None = None
    secret: bool = False
    help: str = ""
    # We hold a value but do not show it (another person's details, to a portal user).
    held: bool = False


@dataclass
class Section:
    key: str
    title: str
    intro: str = ""
    fields: list = field(default_factory=list)
    held: str = ""  # confirmation sections: what Companies House holds


# ---------------------------------------------------------------- secrets in answers


def seal(value: str) -> str:
    """Tax references are encrypted before they are stored in an answer."""
    return ENC_PREFIX + encrypt(value) if value else ""


def unseal(value: str) -> str:
    if isinstance(value, str) and value.startswith(ENC_PREFIX):
        return decrypt(value[len(ENC_PREFIX) :])
    return value or ""


def shown(field_: Field, value: str) -> str:
    """The text for an answer: masked when the field is secret."""
    if not value:
        return ""
    return mask(unseal(value)) if field_.secret else value


# ---------------------------------------------------------------- confirmation statement


def _people(client: Client, role: str):
    return [
        link
        for link in client.client_contacts.filter(resigned_on__isnull=True).select_related(
            "contact"
        )
        if role in (link.roles or [])
    ]


def _names(links) -> str:
    return "\n".join(f"{link.contact.full_name} ({', '.join(link.role_labels)})" for link in links)


def confirmation_sections(client: Client) -> list[Section]:
    officers = _people(client, ClientContact.Role.DIRECTOR) + _people(
        client, ClientContact.Role.SECRETARY
    )
    pscs = _people(client, ClientContact.Role.PSC)
    holders = _people(client, ClientContact.Role.SHAREHOLDER)
    holders_text = "\n".join(
        f"{link.contact.full_name}"
        + (f", {link.shareholding_percent}%" if link.shareholding_percent is not None else "")
        for link in holders
    )
    activity = ", ".join(p for p in (client.sic_codes, client.nature_of_business) if p)
    return [
        Section("registered_office", "Registered office", held=client.registered_office),
        Section("officers", "Directors and secretary", held=_names(officers)),
        Section("psc", "People with significant control", held=_names(pscs)),
        Section("business_activity", "Business activity (SIC codes)", held=activity),
        Section(
            "shareholders",
            "Shareholders and share capital",
            intro="Companies House does not list these in the information we receive.",
            held=holders_text,
        ),
        Section("registered_email", "Registered email address", held=client.email),
    ]


# ---------------------------------------------------------------- client details


def _must_identify(client: Client) -> list[ClientContact]:
    wanted = {"director", "psc", "partner", "member", "trustee"}
    links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
    return [link for link in links if link.is_main or wanted & set(link.roles or [])]


def person_key(contact: Contact, attr: str) -> str:
    return f"p_{contact.public_id.hex}_{attr}"


def _date_text(value: date | None) -> str:
    return value.isoformat() if value else ""


def details_sections(client: Client, viewer: Contact | None = None) -> list[Section]:
    """viewer: the portal user filling the form. Others' personal details are never shown to them."""
    business = Section(
        "business",
        "The business",
        fields=[
            Field(
                "trading_name",
                "Trading name",
                current=client.trading_name,
                target=("client", "trading_name"),
            ),
            Field(
                "address",
                "Business address",
                "textarea",
                current=client.correspondence_address or client.registered_office,
                target=("client", "correspondence_address"),
            ),
            Field("start_date", "When did you start trading?", "date"),
            Field(
                "nature_of_business",
                "What does the business do?",
                "textarea",
                current=client.nature_of_business,
                target=("client", "nature_of_business"),
            ),
        ],
    )
    people_fields = []
    for link in _must_identify(client):
        contact = link.contact
        own = viewer is None or viewer.pk == contact.pk
        dob, home = _date_text(contact.date_of_birth), contact.home_address
        people_fields += [
            Field(
                person_key(contact, "dob"),
                f"{contact.full_name}: date of birth",
                "date",
                current=dob if own else "",
                held=bool(dob) and not own,
                target=("contact", contact.pk, "date_of_birth"),
            ),
            Field(
                person_key(contact, "home_address"),
                f"{contact.full_name}: home address",
                "textarea",
                current=home if own else "",
                held=bool(home) and not own,
                target=("contact", contact.pk, "home_address"),
            ),
        ]
    people = Section(
        "people",
        "People we must identify",
        intro="We are required by law to check who we act for. These details are kept private.",
        fields=people_fields,
    )
    tax = [
        Field(
            "vat_number", "VAT number", current=client.vat_number, target=("client", "vat_number")
        ),
        Field(
            "paye_reference",
            "PAYE reference",
            current=client.paye_reference,
            target=("client", "paye_reference"),
        ),
    ]
    if client.is_company:
        tax.insert(
            0,
            Field(
                "company_utr",
                "Company UTR",
                "secret",
                secret=True,
                current=mask(client.company_utr) if client.company_utr else "",
                target=("client", "company_utr"),
            ),
        )
    for link in _must_identify(client):
        contact = link.contact
        own = viewer is None or viewer.pk == contact.pk
        utr, ni = contact.personal_utr, contact.ni_number
        tax += [
            Field(
                person_key(contact, "utr"),
                f"{contact.full_name}: personal UTR",
                "secret",
                secret=True,
                current=mask(utr) if utr and own else "",
                held=bool(utr) and not own,
                target=("contact", contact.pk, "personal_utr"),
            ),
            Field(
                person_key(contact, "ni"),
                f"{contact.full_name}: National Insurance number",
                "secret",
                secret=True,
                current=mask(ni) if ni and own else "",
                held=bool(ni) and not own,
                target=("contact", contact.pk, "ni_number"),
            ),
        ]
    taxes = Section("tax", "Tax references", fields=tax)
    other = Section(
        "other",
        "Accounting software and your previous accountant",
        fields=[
            Field("software", "Accounting software you use now (if any)"),
            Field("prev_name", "Previous accountant: name or firm"),
            Field("prev_email", "Previous accountant: email address"),
        ],
    )
    services = Section(
        "services",
        "Services agreed",
        fields=[
            Field(
                "services_ok",
                "Is the list of services we agreed correct? Tell us what differs.",
                "textarea",
            )
        ],
    )
    return [business, people, taxes, other, services]


def all_fields(sections) -> list[Field]:
    return [f for section in sections for f in section.fields]
