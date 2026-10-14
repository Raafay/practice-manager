"""Data protection: the retention report, the subject access export and removing a
person for good (spec 01 section 10, spec 12 Stage 13 items 6 and 7).

Nothing here deletes anything on its own. The report lists; the owner decides.
"""

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps import events

from .models import Client, ClientContact, Contact, Document
from .services import require


def _request_model():
    from apps.portal.models import Request

    return Request


# A hidden document is listed once it has been hidden this long.
HIDDEN_DOCUMENT_DAYS = 30
ENDED = (Client.Status.FORMER, Client.Status.LOST)


# ---------------------------------------------------------------- the report


@dataclass
class RetentionReport:
    today: date
    clients: list = field(default_factory=list)  # every retention date has passed
    aml_only: list = field(default_factory=list)  # AML date passed, client records still kept
    people: list = field(default_factory=list)  # nobody keeps these people any more
    hidden_documents: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.clients) + len(self.aml_only) + len(self.people) + len(self.hidden_documents)
        )

    def counts(self) -> dict:
        return {
            "clients": len(self.clients),
            "aml_only": len(self.aml_only),
            "people": len(self.people),
            "hidden_documents": len(self.hidden_documents),
        }


def _past(value: date | None, today: date) -> bool:
    return value is not None and value < today


def client_is_past_retention(client: Client, today: date) -> bool:
    """Ended, and no retention date still runs. A lost prospect has no dates at all."""
    if client.status not in ENDED:
        return False
    dates = [client.retain_until, client.aml_retain_until]
    return all(value is None or value < today for value in dates)


def build_report(today: date | None = None) -> RetentionReport:
    today = today or timezone.localdate()
    report = RetentionReport(today=today)
    ended = Client.objects.filter(status__in=ENDED).order_by("retain_until", "name")
    for client in ended:
        if client.status == Client.Status.FORMER and client.retain_until is None:
            continue  # a former client always has dates; none means it was never set
        if client_is_past_retention(client, today):
            report.clients.append(client)
        elif _past(client.aml_retain_until, today):
            report.aml_only.append(client)
    for contact in Contact.objects.order_by("last_name", "first_name"):
        if purge_block(contact, today) == "":
            report.people.append(contact)
    cutoff = timezone.now() - timedelta(days=HIDDEN_DOCUMENT_DAYS)
    report.hidden_documents = list(
        Document.objects.filter(deleted_at__lt=cutoff)
        .select_related("client")
        .order_by("deleted_at")
    )
    return report


# ---------------------------------------------------------------- one person


def clients_touching(contact: Contact):
    """Every client that holds something about this person: links (even resigned),
    identity checks, documents about them, HMRC authorisations and requests."""
    return Client.objects.filter(
        Q(client_contacts__contact=contact)
        | Q(identity_checks__contact=contact)
        | Q(documents__contact=contact)
        | Q(agent_authorisations__contact=contact)
        | Q(requests__contact=contact)
    ).distinct()


def purge_block(contact: Contact, today: date | None = None) -> str:
    """Why this person's records cannot be removed yet, or "" if they can."""
    today = today or timezone.localdate()
    for client in clients_touching(contact):
        if client.status not in ENDED:
            return f"{client.name} is still a client (status: {client.get_status_display()})."
        if not client_is_past_retention(client, today):
            kept = max(d for d in (client.retain_until, client.aml_retain_until) if d)
            return f"{client.name}'s records must be kept until {kept:%d/%m/%Y}."
    return ""


def _value(value):
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _messages_to(contact: Contact):
    from apps.comms.models import QueuedMessage

    sent = QueuedMessage.objects.filter(state="sent")
    match = Q(contact=contact)
    if contact.email:
        match |= Q(to__icontains=contact.email) | Q(cc__icontains=contact.email)
    return sent.filter(match).order_by("sent_at")


def subject_access_zip(actor, contact: Contact) -> tuple[str, bytes]:
    """Everything held about one person, as a ZIP of data and files. Logged."""
    require(actor, "retention.manage")
    data = {
        "person": {
            f.name: _value(getattr(contact, f.name))
            for f in Contact._meta.fields
            if f.name not in ("id", "portal_user")
        },
        "clients": [
            {
                "client": link.client.name,
                "roles": link.roles or [],
                "main_contact": link.is_main,
                "portal_access": link.portal_access,
                "appointed_on": _value(getattr(link, "appointed_on", None)),
                "resigned_on": _value(link.resigned_on),
            }
            for link in ClientContact.objects.filter(contact=contact).select_related("client")
        ],
        "identity_checks": [
            {
                "client": check.client.name,
                "state": check.get_state_display(),
                "method": check.get_method_display() if check.method else "",
                "document_type": check.document_type,
                "verified_at": _value(check.verified_at),
            }
            for check in contact.identity_checks.select_related("client")
        ],
        "messages": [
            {
                "sent": _value(message.sent_at),
                "subject": message.subject,
                "to": message.to,
                "text": message.body_text,
            }
            for message in _messages_to(contact)
        ],
        "requests": [
            {
                "received": _value(r.received_at or r.created_at),
                "subject": r.subject,
                "text": r.body,
            }
            for r in _request_model().objects.filter(contact=contact).order_by("created_at")
        ],
    }
    documents = list(Document.objects.filter(contact=contact).order_by("created_at"))
    data["documents"] = [
        {
            "title": d.title,
            "file": f"files/{index:03d}-{d.original_name}",
            "added": _value(d.created_at),
            "hidden": bool(d.deleted_at),
        }
        for index, d in enumerate(documents, start=1)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "README.txt",
            "Everything the practice holds about one person, for a subject access request.\n"
            "person.json: the details, links to clients, identity checks, messages sent and\n"
            "requests received. files/: documents about this person.\n"
            f"Made on {timezone.localdate():%d/%m/%Y}.\n",
        )
        archive.writestr("person.json", json.dumps(data, indent=2, ensure_ascii=False))
        for entry, document in zip(data["documents"], documents, strict=True):
            if not document.file:
                continue
            try:
                with document.file.open("rb") as handle:
                    archive.writestr(entry["file"], handle.read())
            except FileNotFoundError:
                archive.writestr(entry["file"] + ".missing.txt", "The file could not be found.")
    events.record(
        actor,
        "export.subject_access",
        f"{actor} exported everything held about a person (contact {contact.pk}).",
        target=contact,
        documents=len(documents),
    )
    return f"subject-access-{contact.pk}-{timezone.localdate():%Y%m%d}.zip", buffer.getvalue()


def purge_contact(actor, contact: Contact, typed_name: str) -> None:
    """Remove a person's records and files for good. Owner only, never while a
    retention period runs. The activity log keeps a line saying it happened."""
    require(actor, "retention.manage")
    if typed_name.strip() != contact.full_name.strip():
        raise ValidationError("Type the person's full name exactly as shown to confirm.")
    block = purge_block(contact)
    if block:
        raise ValidationError(block)
    stored = [
        (d.file.storage, d.file.name) for d in Document.objects.filter(contact=contact) if d.file
    ]
    reference = contact.pk
    portal_user = contact.portal_user
    with transaction.atomic():
        # Written first, with no link to the person, so it survives the delete. No name:
        # the line itself must not keep the personal data that was removed.
        events.record(
            actor,
            "contact.purged",
            f"{actor} removed a person's records for good (contact {reference}).",
            contact_id=reference,
            documents=len(stored),
        )
        Document.objects.filter(contact=contact).delete()
        contact.delete()
        if portal_user is not None and portal_user.is_portal:
            portal_user.is_active = False
            portal_user.email = f"removed-{portal_user.pk}@invalid.example"
            portal_user.name = "Removed person"
            portal_user.set_unusable_password()
            portal_user.save()
    for storage, name in stored:
        storage.delete(name)
