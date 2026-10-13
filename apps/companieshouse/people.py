"""Officers and owners from Companies House as contacts on a client.

A person who is a current officer or owner gets a contact and a link with roles.
Corporate officers and owners are listed on the Companies House tab only.
Nobody is deleted: a person who has left is marked resigned on the link.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, ClientContact, Contact

TITLES = {
    "mr", "mrs", "ms", "miss", "mx", "dr", "prof", "professor", "sir", "dame", "lord",
    "lady", "rev", "revd", "reverend", "hon",
}  # fmt: skip

ROLES = {
    "director": ClientContact.Role.DIRECTOR,
    "nominee-director": ClientContact.Role.DIRECTOR,
    "secretary": ClientContact.Role.SECRETARY,
    "nominee-secretary": ClientContact.Role.SECRETARY,
    "llp-member": ClientContact.Role.MEMBER,
    "llp-designated-member": ClientContact.Role.MEMBER,
    "member": ClientContact.Role.MEMBER,
}


def _word_case(word: str) -> str:
    """ "SMITH-JONES" to "Smith-Jones", "O'BRIEN" to "O'Brien", "MCDONALD" to "McDonald"."""
    parts = re.split(r"([-'’])", word.lower())
    out = []
    for part in parts:
        if part in "-'’":
            out.append(part)
            continue
        text = part[:1].upper() + part[1:]
        if text.startswith("Mc") and len(text) > 2:
            text = "Mc" + text[2:3].upper() + text[3:]
        out.append(text)
    return "".join(out)


def name_case(text: str) -> str:
    return " ".join(_word_case(w) for w in text.split())


def parse_officer_name(raw: str) -> dict:
    """Companies House gives "SURNAME, Forenames", sometimes with a title after a second comma.

    Returns title, first_name, middle_name and last_name.
    """
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    title = ""
    if len(parts) >= 3 and parts[-1].lower().rstrip(".") in TITLES:
        title = parts.pop().rstrip(".")
    if len(parts) >= 2:
        surname, forenames = parts[0], " ".join(parts[1:])
    else:
        words = (parts[0] if parts else "").split()
        surname, forenames = (words[-1], " ".join(words[:-1])) if words else ("", "")
    names = forenames.split()
    if names and names[0].lower().rstrip(".") in TITLES and not title:
        title = names.pop(0).rstrip(".")
    return {
        "title": name_case(title),
        "first_name": name_case(names[0]) if names else "",
        "middle_name": name_case(" ".join(names[1:])),
        "last_name": name_case(surname),
    }


def officer_id(item: dict) -> str:
    """The id that identifies a person across companies, from links.officer.appointments."""
    path = (item.get("links") or {}).get("officer", {}).get("appointments", "")
    match = re.match(r"^/officers/([^/]+)/appointments", path)
    return match.group(1) if match else ""


def appointment_key(item: dict) -> str:
    """Identifies one appointment or one owner entry on this company."""
    links = item.get("links") or {}
    return (
        links.get("self")
        or f"{item.get('name', '')}|{item.get('officer_role') or item.get('kind')}"
    )


def is_corporate_officer(item: dict) -> bool:
    return "corporate" in (item.get("officer_role") or "")


def is_person_owner(item: dict) -> bool:
    return (item.get("kind") or "").startswith("individual")


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


@dataclass
class Person:
    """One human being found in the officers and owners lists of a company."""

    title: str
    first_name: str
    middle_name: str
    last_name: str
    birth_month: int | None
    birth_year: int | None
    officer_id: str = ""
    nationality: str = ""
    country_of_residence: str = ""
    occupation: str = ""
    verified_on: date | None = None
    roles: set = field(default_factory=set)  # roles held now
    appointed_on: date | None = None
    current: bool = False
    ended_on: date | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def key(self) -> tuple:
        if self.officer_id:
            return ("id", self.officer_id)
        return (
            "name",
            self.first_name.lower(),
            self.last_name.lower(),
            self.birth_month,
            self.birth_year,
        )

    def same_person(self, other: "Person") -> bool:
        return (
            self.first_name.lower() == other.first_name.lower()
            and self.last_name.lower() == other.last_name.lower()
            and self.birth_month == other.birth_month
            and self.birth_year == other.birth_year
            and self.birth_year is not None
        )


def _birth(item: dict) -> tuple[int | None, int | None]:
    dob = item.get("date_of_birth") or {}
    try:
        return int(dob.get("month")), int(dob.get("year"))
    except (TypeError, ValueError):
        return None, None


def _verified(item: dict) -> date | None:
    return parse_date((item.get("identity_verification_details") or {}).get("identity_verified_on"))


def _add_role(person: Person, role: str, start, end) -> None:
    if end is None:
        person.roles.add(role)
        person.current = True
        if start and (person.appointed_on is None or start < person.appointed_on):
            person.appointed_on = start
    elif person.ended_on is None or end > person.ended_on:
        person.ended_on = end


def people_from(officers: list[dict], owners: list[dict]) -> list[Person]:
    """Merge officers and owners into people. An owner who is also an officer is one person."""
    people: list[Person] = []
    for item in officers:
        if is_corporate_officer(item):
            continue
        month, year = _birth(item)
        person = Person(
            **parse_officer_name(item.get("name", "")),
            birth_month=month,
            birth_year=year,
            officer_id=officer_id(item),
            nationality=item.get("nationality", ""),
            country_of_residence=item.get("country_of_residence", ""),
            occupation=item.get("occupation", ""),
            verified_on=_verified(item),
        )
        existing = next((p for p in people if p.key() == person.key()), None)
        if existing is None:
            people.append(person)
            existing = person
        role = ROLES.get(item.get("officer_role", ""), ClientContact.Role.OTHER)
        _add_role(
            existing,
            role,
            parse_date(item.get("appointed_on")),
            parse_date(item.get("resigned_on")),
        )
    for item in owners:
        if not is_person_owner(item):
            continue
        elements = item.get("name_elements") or {}
        month, year = _birth(item)
        if elements.get("surname"):
            names = {
                "title": name_case(elements.get("title", "")),
                "first_name": name_case(elements.get("forename", "")),
                "middle_name": name_case(elements.get("middle_name", "")),
                "last_name": name_case(elements.get("surname", "")),
            }
        else:
            names = parse_officer_name(item.get("name", ""))
        person = Person(
            **names,
            birth_month=month,
            birth_year=year,
            nationality=item.get("nationality", ""),
            country_of_residence=item.get("country_of_residence", ""),
            verified_on=_verified(item),
        )
        existing = next((p for p in people if p.same_person(person)), None)
        if existing is None:
            people.append(person)
            existing = person
        elif not existing.verified_on:
            existing.verified_on = person.verified_on
        _add_role(
            existing,
            ClientContact.Role.PSC,
            parse_date(item.get("notified_on")),
            parse_date(item.get("ceased_on")),
        )
    return [p for p in people if p.first_name and p.last_name]


def find_contact(person: Person) -> Contact | None:
    """By Companies House officer id, then by name with month and year of birth."""
    if person.officer_id:
        found = Contact.objects.filter(ch_officer_id=person.officer_id).first()
        if found:
            return found
    if person.birth_year is None or person.birth_month is None:
        return None
    candidates = Contact.objects.filter(
        first_name__iexact=person.first_name, last_name__iexact=person.last_name
    )
    for contact in candidates:
        if (contact.birth_month, contact.birth_year) == (person.birth_month, person.birth_year):
            return contact
        dob = contact.date_of_birth
        if dob and (dob.month, dob.year) == (person.birth_month, person.birth_year):
            return contact
    return None


@dataclass
class PeopleResult:
    contacts_created: int = 0
    links_created: int = 0
    links_updated: int = 0


def apply_people(actor, client: Client, people: list[Person]) -> PeopleResult:
    """Create, match and link contacts. Running it twice changes nothing the second time."""
    result = PeopleResult()
    for person in people:
        with transaction.atomic():
            contact = find_contact(person)
            if contact is None:
                if not person.current:
                    continue  # people who left before we knew them are listed, not added
                contact = client_services.create_contact(
                    actor,
                    title=person.title,
                    first_name=person.first_name,
                    middle_name=person.middle_name,
                    last_name=person.last_name,
                    birth_month=person.birth_month,
                    birth_year=person.birth_year,
                    ch_officer_id=person.officer_id,
                    nationality=person.nationality,
                    country_of_residence=person.country_of_residence,
                    occupation=person.occupation,
                )
                result.contacts_created += 1
            _fill_contact(contact, person)
            link = ClientContact.objects.filter(client=client, contact=contact).first()
            if link is None:
                if not person.current:
                    continue
                client_services.add_contact(
                    actor,
                    client,
                    contact,
                    roles=sorted(person.roles),
                    appointed_on=person.appointed_on,
                    source=ClientContact.Source.COMPANIES_HOUSE,
                    can_sign=ClientContact.Role.DIRECTOR in person.roles
                    or ClientContact.Role.MEMBER in person.roles,
                )
                result.links_created += 1
                continue
            if _update_link(link, person):
                result.links_updated += 1
    return result


def _fill_contact(contact: Contact, person: Person) -> None:
    """Fill gaps on the contact from Companies House. Never overwrite what staff typed."""
    changed = []
    if person.officer_id and not contact.ch_officer_id:
        contact.ch_officer_id = person.officer_id
        changed.append("ch_officer_id")
    if person.birth_year and contact.birth_year is None:
        contact.birth_month, contact.birth_year = person.birth_month, person.birth_year
        changed += ["birth_month", "birth_year"]
    if person.verified_on and not contact.ch_identity_verified:
        contact.ch_identity_verified = True
        contact.ch_identity_verified_on = person.verified_on
        changed += ["ch_identity_verified", "ch_identity_verified_on"]
    for name in ("nationality", "country_of_residence", "occupation"):
        if getattr(person, name) and not getattr(contact, name):
            setattr(contact, name, getattr(person, name))
            changed.append(name)
    if changed:
        contact.save(update_fields=[*changed, "updated_at"])


def _update_link(link: ClientContact, person: Person) -> bool:
    """Add new roles, and mark resigned when every Companies House role has ended."""
    fields = []
    roles = sorted(set(link.roles) | person.roles)
    if roles != sorted(link.roles):
        link.roles = roles
        fields.append("roles")
    resigned = None if person.current else person.ended_on
    if link.resigned_on != resigned:
        link.resigned_on = resigned
        fields.append("resigned_on")
    if person.current and person.appointed_on and link.appointed_on is None:
        link.appointed_on = person.appointed_on
        fields.append("appointed_on")
    if fields:
        link.save(update_fields=[*fields, "updated_at"])
        events.record(
            None,
            "contact.link_changed",
            f"Companies House: {link.contact.full_name} at {link.client.name} updated"
            + (f" (resigned {link.resigned_on:%d/%m/%Y})." if link.resigned_on else "."),
            client=link.client,
            target=link.contact,
            fields=fields,
        )
    return bool(fields)
