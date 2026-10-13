"""Business rules for clients, people, links, notes and documents.

Views call these. Each change writes an activity event with a readable sentence.
Nothing here ever puts the value of an encrypted field into an event.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps import events
from apps.core.dates import add_months
from apps.core.fields import EncryptedTextField
from apps.core.models import PracticeSettings
from apps.events.services import changes

from .models import (
    Client,
    ClientContact,
    ClientLink,
    Contact,
    Document,
    Note,
)

# What each status may become by hand. Later stages add the proper routes
# (the onboarding gate in Stage 7, proposal acceptance in Stage 9).
STATUS_MOVES = {
    "prospect": ("onboarding", "lost"),
    "onboarding": ("active", "paused", "former"),
    "active": ("paused", "former"),
    "paused": ("active", "former"),
    "former": ("active",),
    "lost": ("prospect",),
}

SENSITIVE_FIELDS = {
    "client": {"company_utr", "ch_auth_code"},
    "contact": {"ni_number", "personal_utr", "ch_personal_code"},
}


def require(actor, right: str) -> None:
    if not actor.can(right):
        raise PermissionDenied


# ---------------------------------------------------------------- clients


def allowed_moves(client: Client) -> list[str]:
    return list(STATUS_MOVES.get(client.status, ()))


def retention_dates(ended_on: date) -> tuple[date, date]:
    """(retain_until, aml_retain_until) for a relationship that ended on ended_on."""
    practice = PracticeSettings.load()
    return (
        add_months(ended_on, 12 * practice.retention_years),
        add_months(ended_on, 12 * practice.aml_retention_years),
    )


def create_client(
    actor,
    *,
    name: str,
    client_type: str,
    manager=None,
    status: str = Client.Status.ACTIVE,
    contact: Contact | None = None,
    **fields,
) -> Client:
    """Make a client. A contact, if given, becomes its main contact."""
    for attempt in range(3):
        try:
            with transaction.atomic():
                client = Client.objects.create(
                    name=name.strip(),
                    client_type=client_type,
                    manager=manager,
                    status=status,
                    client_since=timezone.localdate() if status == Client.Status.ACTIVE else None,
                    **fields,
                )
            break
        except IntegrityError:  # two people took the same reference at once
            if attempt == 2:
                raise
    events.record(
        actor,
        "client.created",
        f"{actor} created client {client.name} ({client.reference}).",
        client=client,
        target=client,
    )
    if contact is not None:
        add_contact(actor, client, contact, is_main=True)
    return client


def update_client(actor, client: Client, form, *, section: str) -> Client:
    """Save a panel form and record which fields changed, by name only for secrets."""
    names = [n for n in form.changed_data if n in form.fields]
    if not names:
        return client
    labels = []
    for name in names:
        if name.startswith("cf_"):
            labels.append(form.fields[name].label)
        elif name.startswith("clear_"):
            labels.append(
                str(form.fields[name].label).replace("Remove the saved ", "").capitalize()
            )
        else:
            labels.append(str(form.fields[name].label or name).capitalize())
    with transaction.atomic():
        client = form.save()
    diff = changes(form.before, form.after())
    events.record(
        actor,
        "client.changed",
        f"{actor} changed {section.lower()} for {client.name}: {', '.join(sorted(set(labels)))}.",
        client=client,
        target=client,
        section=section,
        fields=diff,
    )
    return client


def change_status(
    actor, client: Client, new_status: str, *, ended_on: date | None = None, reason: str = ""
) -> Client:
    require(actor, "clients.status")
    if new_status not in allowed_moves(client):
        raise ValidationError(
            f"A {client.get_status_display().lower()} client cannot be changed to "
            f"{Client.Status(new_status).label.lower()}."
        )
    old = client.status
    client.status = new_status
    if new_status == Client.Status.FORMER:
        ended = ended_on or timezone.localdate()
        client.relationship_ended_on = ended
        client.retain_until, client.aml_retain_until = retention_dates(ended)
    elif old == Client.Status.FORMER:
        client.relationship_ended_on = None
        client.retain_until = client.aml_retain_until = None
    if new_status == Client.Status.ACTIVE and not client.client_since:
        client.client_since = timezone.localdate()
    client.save()
    events.record(
        actor,
        "client.status_changed",
        f"{actor} changed {client.name} from {Client.Status(old).label} to "
        f"{Client.Status(new_status).label}.",
        client=client,
        target=client,
        old=old,
        new=new_status,
        reason=reason,
    )
    return client


def archive_client(actor, client: Client, reason: str) -> Client:
    require(actor, "clients.archive")
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say why this client is being archived.")
    client.archived_at = timezone.now()
    client.archived_by = actor
    client.archive_reason = reason[:300]
    client.save(update_fields=["archived_at", "archived_by", "archive_reason", "updated_at"])
    events.record(
        actor,
        "client.archived",
        f"{actor} archived {client.name}: {reason}",
        client=client,
        target=client,
        reason=reason,
    )
    return client


def restore_client(actor, client: Client) -> Client:
    require(actor, "clients.archive")
    client.archived_at = None
    client.archived_by = None
    client.archive_reason = ""
    client.save(update_fields=["archived_at", "archived_by", "archive_reason", "updated_at"])
    events.record(
        actor, "client.restored", f"{actor} restored {client.name}.", client=client, target=client
    )
    return client


def delete_block(client: Client, today: date | None = None) -> str:
    """Why this client cannot be deleted for good, or an empty string."""
    today = today or timezone.localdate()
    for label, until in (
        ("Client records", client.retain_until),
        ("AML records", client.aml_retain_until),
    ):
        if until and until >= today:
            return f"{label} must be kept until {until:%d/%m/%Y}."
    return ""


def delete_client(actor, client: Client, typed_name: str) -> None:
    require(actor, "clients.delete")
    if typed_name.strip() != client.name:
        raise ValidationError("Type the client's name exactly as shown to confirm.")
    block = delete_block(client)
    if block:
        raise ValidationError(block)
    label = f"{client.name} ({client.reference})"
    stored = list(client.documents.exclude(file="").values_list("file", flat=True))
    storage = Document._meta.get_field("file").storage
    with transaction.atomic():
        # Written first, with no client link, so it survives the delete.
        events.record(
            actor,
            "client.deleted",
            f"{actor} deleted client {label} for good.",
            client_label=label,
        )
        client.delete()
    for name in stored:
        storage.delete(name)


# ---------------------------------------------------------------- search


def search_clients(query: str, *, include_archived: bool = False):
    """Clients matching every word of the query in a name, number, contact name or email."""
    queryset = Client.objects.all()
    if not include_archived:
        queryset = queryset.not_archived()
    for word in query.split():
        queryset = queryset.filter(
            Q(name__icontains=word)
            | Q(trading_name__icontains=word)
            | Q(company_number__icontains=word)
            | Q(reference__icontains=word)
            | Q(email__icontains=word)
            | Q(client_contacts__contact__first_name__icontains=word)
            | Q(client_contacts__contact__last_name__icontains=word)
            | Q(client_contacts__contact__email__icontains=word)
        )
    return queryset.distinct().order_by("name")


def find_matching_contacts(*, email: str = "", first_name: str = "", last_name: str = ""):
    """Existing people who may be the same person, by email or by name."""
    condition = Q(pk__in=[])
    if email.strip():
        condition |= Q(email__iexact=email.strip())
    if first_name.strip() and last_name.strip():
        condition |= Q(first_name__iexact=first_name.strip(), last_name__iexact=last_name.strip())
    return Contact.objects.filter(condition)


def search_contacts(query: str):
    queryset = Contact.objects.all()
    for word in query.split():
        queryset = queryset.filter(
            Q(first_name__icontains=word)
            | Q(last_name__icontains=word)
            | Q(email__icontains=word)
            | Q(preferred_name__icontains=word)
        )
    return queryset.order_by("last_name", "first_name")


# ---------------------------------------------------------------- contacts


def create_contact(actor, **fields) -> Contact:
    contact = Contact.objects.create(**fields)
    events.record(
        actor,
        "contact.created",
        f"{actor} added the person {contact.full_name}.",
        target=contact,
    )
    return contact


def _record_for_clients(actor, contact: Contact, verb: str, summary: str, **data) -> None:
    """One event per client the person is linked to, so each timeline shows it."""
    clients = list(Client.objects.filter(client_contacts__contact=contact).distinct())
    if not clients:
        events.record(actor, verb, summary, target=contact, **data)
    for client in clients:
        events.record(actor, verb, summary, client=client, target=contact, **data)


def update_contact(actor, contact: Contact, form) -> Contact:
    names = [n for n in form.changed_data if n in form.fields]
    if not names:
        return contact
    labels = sorted({str(form.fields[n].label or n).capitalize() for n in names})
    contact = form.save()
    _record_for_clients(
        actor,
        contact,
        "contact.changed",
        f"{actor} changed details for {contact.full_name}: {', '.join(labels)}.",
        fields=changes(form.before, form.after()),
    )
    return contact


def add_contact(
    actor, client: Client, contact: Contact, *, is_main: bool | None = None, **fields
) -> ClientContact:
    """Link a person to a client. The first person linked becomes the main contact."""
    if ClientContact.objects.filter(client=client, contact=contact).exists():
        raise ValidationError(f"{contact.full_name} is already linked to {client.name}.")
    with transaction.atomic():
        if is_main is None:
            is_main = not client.client_contacts.filter(is_main=True).exists()
        if is_main:
            client.client_contacts.filter(is_main=True).update(is_main=False)
        link = ClientContact.objects.create(
            client=client, contact=contact, is_main=is_main, **fields
        )
    events.record(
        actor,
        "contact.linked",
        f"{actor} linked {contact.full_name} to {client.name}"
        f"{' as main contact' if is_main else ''}.",
        client=client,
        target=contact,
    )
    return link


def save_client_contact(actor, link: ClientContact, form) -> ClientContact:
    names = [n for n in form.changed_data if n in form.fields]
    with transaction.atomic():
        if form.cleaned_data.get("is_main"):
            ClientContact.objects.filter(client=link.client, is_main=True).exclude(
                pk=link.pk
            ).update(is_main=False)
        link = form.save()
    if names:
        labels = sorted({str(form.fields[n].label or n).capitalize() for n in names})
        events.record(
            actor,
            "contact.link_changed",
            f"{actor} changed {link.contact.full_name} at {link.client.name}: {', '.join(labels)}.",
            client=link.client,
            target=link.contact,
            fields=changes(form.before, form.after()),
        )
    return link


def unlink_contact(actor, link: ClientContact) -> None:
    """Remove the link. The person is never deleted."""
    client, contact = link.client, link.contact
    link.delete()
    events.record(
        actor,
        "contact.unlinked",
        f"{actor} unlinked {contact.full_name} from {client.name}.",
        client=client,
        target=contact,
    )


def create_personal_tax_client(actor, contact: Contact, from_client: Client | None) -> Client:
    """A new Individual client with this person as main contact, linked to the other client."""
    existing = Client.objects.filter(
        client_type=Client.Type.INDIVIDUAL,
        client_contacts__contact=contact,
        client_contacts__is_main=True,
    ).first()
    if existing:
        raise ValidationError(
            f"{contact.full_name} already has a personal client: {existing.name} "
            f"({existing.reference})."
        )
    with transaction.atomic():
        client = create_client(
            actor,
            name=contact.full_name,
            client_type=Client.Type.INDIVIDUAL,
            manager=from_client.manager if from_client else None,
            partner=from_client.partner if from_client else None,
            email=contact.email,
            phone=contact.mobile or contact.phone,
            contact=contact,
        )
        if from_client is not None:
            add_link(
                actor,
                from_client,
                client,
                ClientLink.Relationship.PERSONAL_TAX,
                f"Personal tax for {contact.full_name}.",
            )
    return client


# ---------------------------------------------------------------- links


def add_link(actor, client: Client, other: Client, relationship: str, note: str = "") -> ClientLink:
    if client.pk == other.pk:
        raise ValidationError("A client cannot be linked to itself.")
    if ClientLink.objects.filter(
        Q(client_a=client, client_b=other) | Q(client_a=other, client_b=client)
    ).exists():
        raise ValidationError(f"{client.name} is already linked to {other.name}.")
    link = ClientLink.objects.create(
        client_a=client, client_b=other, relationship=relationship, note=note.strip()
    )
    label = link.get_relationship_display().lower()
    for side, far in ((client, other), (other, client)):
        events.record(
            actor,
            "link.added",
            f"{actor} linked {side.name} and {far.name} ({label}).",
            client=side,
            target=link,
        )
    return link


def remove_link(actor, link: ClientLink) -> None:
    a, b = link.client_a, link.client_b
    link.delete()
    for side in (a, b):
        events.record(
            actor,
            "link.removed",
            f"{actor} removed the link between {a.name} and {b.name}.",
            client=side,
        )


def linked_clients(client: Client):
    """(link, other client) pairs for both directions."""
    links = ClientLink.objects.filter(Q(client_a=client) | Q(client_b=client)).select_related(
        "client_a", "client_b"
    )
    return [(link, link.other(client)) for link in links]


# ---------------------------------------------------------------- notes


def add_note(actor, client: Client, text: str, *, kind: str = Note.Kind.NOTE, pinned=False) -> Note:
    text = text.strip()
    if not text:
        raise ValidationError("Write something first.")
    note = Note.objects.create(
        client=client, kind=kind, text=text, author=actor, pinned=pinned and kind == Note.Kind.NOTE
    )
    if kind == Note.Kind.CALL:
        verb, summary = "call.logged", f"{actor} logged a call with {client.name}."
    else:
        verb, summary = "note.added", f"{actor} added a note to {client.name}."
    events.record(
        actor, verb, summary, client=client, target=note, note_id=note.pk, text=text[:1000]
    )
    return note


def toggle_pin(actor, note: Note) -> Note:
    note.pinned = not note.pinned
    note.save(update_fields=["pinned", "updated_at"])
    events.record(
        actor,
        "note.pinned" if note.pinned else "note.unpinned",
        f"{actor} {'pinned' if note.pinned else 'unpinned'} a note on {note.client.name}.",
        client=note.client,
        target=note,
    )
    return note


# ---------------------------------------------------------------- sensitive values


def reveal_value(actor, instance, field_name: str, *, client: Client | None = None) -> str:
    """Return a decrypted value and log that it was shown. Only listed fields may be shown."""
    kind = "client" if isinstance(instance, Client) else "contact"
    if field_name not in SENSITIVE_FIELDS[kind]:
        raise PermissionDenied
    field = instance._meta.get_field(field_name)
    assert isinstance(field, EncryptedTextField)
    value = getattr(instance, field_name)
    owner_label = instance.name if kind == "client" else instance.full_name
    events.record(
        actor,
        "sensitive.revealed",
        f"{actor} showed the {field.verbose_name} of {owner_label}.",
        client=instance if kind == "client" else client,
        target=instance,
        field=field_name,
    )
    return value or ""


# ---------------------------------------------------------------- documents


def store_document(
    actor, client: Client, upload, *, category: str, contact=None, sensitive=False
) -> Document:
    from .documents import check_document_upload

    content_type = check_document_upload(upload)
    sensitive = sensitive or category in Document.SENSITIVE_BY_DEFAULT
    title = upload.name.rsplit(".", 1)[0][:200] or upload.name[:200]
    document = Document(
        client=client,
        contact=contact,
        category=category,
        title=title,
        original_name=upload.name[:255],
        size=upload.size,
        content_type=content_type,
        sensitive=sensitive,
        uploaded_by=actor,
        source=Document.Source.STAFF,
    )
    document.file.save(upload.name, upload, save=False)
    document.save()
    events.record(
        actor,
        "document.uploaded",
        f"{actor} uploaded {document.title} to {client.name}{' (sensitive)' if sensitive else ''}.",
        client=client,
        target=document,
        category=category,
        sensitive=sensitive,
    )
    return document


def update_document(actor, document: Document, form) -> Document:
    names = [n for n in form.changed_data if n in form.fields]
    document = form.save()
    if names:
        events.record(
            actor,
            "document.changed",
            f"{actor} changed {document.title} on {document.client.name}.",
            client=document.client,
            target=document,
            fields=changes(form.before, form.after()),
        )
    return document


def can_open_document(user, document: Document) -> bool:
    return not document.sensitive or user.can("documents.sensitive")


def record_document_access(actor, document: Document, *, download: bool) -> None:
    """Each view or download of a sensitive document is logged."""
    if not document.sensitive:
        return
    verb = "document.downloaded" if download else "document.viewed"
    events.record(
        actor,
        verb,
        f"{actor} {'downloaded' if download else 'viewed'} the sensitive document "
        f"{document.title} for {document.client.name}.",
        client=document.client,
        target=document,
    )


def delete_document(actor, document: Document) -> None:
    document.soft_delete(actor)
    events.record(
        actor,
        "document.deleted",
        f"{actor} deleted {document.title} from {document.client.name}. It is hidden, not erased.",
        client=document.client,
        target=document,
    )


def purge_document(actor, document: Document) -> None:
    """Remove a hidden document and its file for good. Owner only."""
    require(actor, "retention.manage")
    if not document.is_deleted:
        raise ValidationError("Delete the document first. Only hidden documents can be removed.")
    client, title = document.client, document.title
    name = document.file.name
    storage = document.file.storage
    document.delete()
    if name:
        storage.delete(name)
    events.record(
        actor,
        "document.purged",
        f"{actor} removed {title} from {client.name} for good.",
        client=client,
    )
