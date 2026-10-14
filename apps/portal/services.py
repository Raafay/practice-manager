"""Portal rules: invitations, things to do, uploads (spec 08 sections 1 to 3)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.clients import services as client_services
from apps.clients.documents import check_document_upload
from apps.clients.models import Client, ClientContact, Contact, Document
from apps.core.models import PracticeSettings
from apps.core.siteurl import absolute

from .models import PortalItem


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


# ---------------------------------------------------------------- access (section 1)


def portal_state(client: Client) -> str:
    """not_invited, invited (nobody has signed in yet) or active."""
    users = [
        link.contact.portal_user
        for link in client.client_contacts.filter(portal_access=True).select_related(
            "contact__portal_user"
        )
        if link.contact.portal_user_id
    ]
    if not users:
        return "not_invited"
    return "active" if any(u.last_login for u in users) else "invited"


PORTAL_STATE_LABELS = {
    "not_invited": ("Portal: not invited", "neutral"),
    "invited": ("Portal: invited", "amber"),
    "active": ("Portal: active", "green"),
}


def invite_blockers(link: ClientContact) -> str:
    contact = link.contact
    if not contact.email:
        return "This person has no email address. Add one first."
    if link.resigned_on:
        return "This person has resigned from the client."
    clash = User.objects.filter(email__iexact=contact.email).exclude(pk=contact.portal_user_id)
    if clash.exists():
        return "That email address already belongs to another account."
    return ""


@transaction.atomic
def invite(actor, link: ClientContact) -> User:
    """Give a contact portal access and email them the portal address. No password is set."""
    problem = invite_blockers(link)
    if problem:
        raise ValidationError(problem)
    contact, client = link.contact, link.client
    user = contact.portal_user
    if user is None:
        user = User.objects.create_user(
            contact.email,
            name=contact.full_name,
            kind=User.Kind.PORTAL,
            role=None,
        )
        contact.portal_user = user
        contact.save(update_fields=["portal_user", "updated_at"])
    else:
        if user.email.lower() != contact.email.lower():
            user.email = contact.email.lower()
        user.is_active = True
        user.save()
    link.portal_access = True
    link.save(update_fields=["portal_access", "updated_at"])
    events.record(
        actor,
        "portal.invited",
        f"{who(actor)} invited {contact.full_name} to the portal for {client.name}.",
        client=client,
        target=contact,
    )
    transaction.on_commit(lambda: _send_invitation(user, client))
    return user


def _send_invitation(user: User, client: Client) -> None:
    from apps.comms.services import sending_address

    practice = PracticeSettings.load()
    address = absolute(reverse("portal:login"))
    EmailMultiAlternatives(
        subject=f"Your {practice.practice_name} client portal",
        body=(
            f"Hello {user.name},\n\n"
            f"{practice.practice_name} has set up a secure portal for {client.name}. "
            "You can sign documents, upload records and send us requests there.\n\n"
            f"Sign in at {address}. Enter this email address and we will send you a "
            "six-digit code. There is no password.\n\n"
            f"{practice.practice_name}"
        ),
        from_email=sending_address(practice),
        to=[user.email],
    ).send()


def withdraw(actor, link: ClientContact) -> None:
    """Switch portal access off for this client. Other clients of the same person are kept."""
    if not link.portal_access:
        return
    link.portal_access = False
    link.save(update_fields=["portal_access", "updated_at"])
    events.record(
        actor,
        "portal.withdrawn",
        f"{who(actor)} withdrew {link.contact.full_name}'s portal access to {link.client.name}.",
        client=link.client,
        target=link.contact,
    )


# ---------------------------------------------------------------- things to do (section 3)


def create_item(
    actor,
    client: Client,
    kind: str,
    title: str,
    *,
    contact: Contact | None = None,
    description: str = "",
    object_id: int | None = None,
    task=None,
    due_date=None,
    reuse: bool = True,
) -> PortalItem:
    """Add a thing to do. An open item of the same kind for the same object is reused."""
    if reuse:
        existing = PortalItem.objects.filter(
            client=client,
            kind=kind,
            state=PortalItem.State.OPEN,
            object_id=object_id,
            task=task,
            contact=contact,
        ).first()
        if existing is not None:
            return existing
    item = PortalItem.objects.create(
        client=client,
        contact=contact,
        kind=kind,
        title=title[:200],
        description=description,
        object_id=object_id,
        task=task,
        due_date=due_date,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    events.record(
        actor,
        "portal.item_created",
        f"“{item.title}” was added to {client.name}'s portal.",
        client=client,
        target=item,
        kind=kind,
    )
    return item


def complete_item(item: PortalItem, contact: Contact | None, *, actor=None) -> PortalItem:
    if item.state != PortalItem.State.OPEN:
        return item
    item.state = PortalItem.State.DONE
    item.completed_at = timezone.now()
    item.completed_by = contact
    item.save(update_fields=["state", "completed_at", "completed_by", "updated_at"])
    events.record(
        actor,
        "portal.item_done",
        f"“{item.title}” was completed in the portal for {item.client.name}.",
        client=item.client,
        target=item,
        actor_label=contact.full_name if contact else "",
    )
    return item


def cancel_item(actor, item: PortalItem) -> PortalItem:
    if item.state == PortalItem.State.OPEN:
        item.state = PortalItem.State.CANCELLED
        item.save(update_fields=["state", "updated_at"])
        events.record(
            actor,
            "portal.item_cancelled",
            f"“{item.title}” was withdrawn from {item.client.name}'s portal.",
            client=item.client,
            target=item,
        )
    return item


def sync_item_for(kind: str, object_id: int, client: Client, *, contact=None) -> None:
    """Close the open item for an object that was dealt with another way (a signed letter)."""
    for item in PortalItem.objects.filter(
        client=client, kind=kind, object_id=object_id, state=PortalItem.State.OPEN
    ):
        complete_item(item, contact)


# ---------------------------------------------------------------- uploads (section 2)


PORTAL_CATEGORIES = [
    (Document.Category.ACCOUNTS, "Accounts"),
    (Document.Category.BOOKKEEPING, "Bookkeeping records"),
    (Document.Category.VAT, "VAT"),
    (Document.Category.PAYROLL, "Payroll"),
    (Document.Category.TAX, "Tax"),
    (Document.Category.IDENTITY, "Identity"),
    (Document.Category.PROOF_OF_ADDRESS, "Proof of address"),
    (Document.Category.OTHER, "Other"),
]


def notify_owner(client: Client, message: str, link: str) -> None:
    from apps.onboarding.services import notify_staff

    notify_staff(client, message, link)


@transaction.atomic
def store_upload(
    user: User, client: Client, upload, *, category: str, note: str = "", task=None
) -> Document:
    """One file from the portal becomes a Document with source `portal`."""
    if category not in dict(PORTAL_CATEGORIES):
        category = Document.Category.OTHER
    content_type = check_document_upload(upload)
    contact = getattr(user, "portal_contact", None)
    title = upload.name.rsplit(".", 1)[0][:200] or upload.name[:200]
    if note:
        title = f"{title} ({note[:60]})"[:200]
    sensitive = category in Document.SENSITIVE_BY_DEFAULT
    document = Document(
        client=client,
        contact=contact,
        category=category,
        title=title,
        original_name=upload.name[:255],
        size=upload.size,
        content_type=content_type,
        sensitive=sensitive,
        shared_with_portal=False,
        uploaded_by=user,
        source=Document.Source.PORTAL,
    )
    document.file.save(upload.name, upload, save=False)
    document.save()
    events.record(
        user,
        "document.uploaded",
        f"{contact.full_name if contact else user} uploaded {document.title} to the portal "
        f"for {client.name}{' (sensitive)' if sensitive else ''}.",
        client=client,
        target=document,
        category=category,
        sensitive=sensitive,
        note=note[:300],
        source="portal",
    )
    if task is not None:
        from apps.tasks import services as task_services

        task_services.attach_document(user, task, document)
    return document


def upload_many(user, client, uploads, *, category, note="", task=None) -> list[Document]:
    if not uploads:
        raise ValidationError("Choose at least one file.")
    if len(uploads) > 10:
        raise ValidationError("Send up to 10 files at a time.")
    documents = []
    with transaction.atomic():
        for upload in uploads:
            documents.append(
                store_upload(user, client, upload, category=category, note=note, task=task)
            )
    link = reverse("clients:documents", args=[client.pk])
    names = ", ".join(d.original_name for d in documents[:3])
    notify_owner(
        client,
        f"{client.name} uploaded {len(documents)} file{'s' if len(documents) != 1 else ''} "
        f"in the portal ({names}{'…' if len(documents) > 3 else ''}).",
        link,
    )
    return documents


# ---------------------------------------------------------------- "That is everything"


def everything_uploaded(item: PortalItem, user: User) -> bool:
    """Tick the step that stops reminders, once, and tell the task owner. Returns True if ticked."""
    from apps.tasks import services as task_services

    contact = getattr(user, "portal_contact", None)
    with transaction.atomic():
        item = PortalItem.objects.select_for_update().get(pk=item.pk)
        if item.state != PortalItem.State.OPEN or item.kind != PortalItem.Kind.UPLOAD_RECORDS:
            return False
        ticked = False
        task = item.task
        if task is not None and not task.is_cancelled:
            step = task.steps.filter(stops_reminders=True, done_at__isnull=True).first()
            if step is not None:
                task_services.toggle_step(user, step, True)
                ticked = True
        complete_item(item, contact, actor=user)
        who_said = contact.full_name if contact else str(user)
        owner = (task.owner if task is not None else None) or client_services_owner(item.client)
        if owner is not None:
            link = (
                task_services.task_url(task)
                if task is not None
                else reverse("clients:documents", args=[item.client.pk])
            )
            events.notify(
                owner, f"{who_said} says {item.client.name} has uploaded everything.", link
            )
    return ticked


def client_services_owner(client: Client):
    from apps.onboarding.services import responsible_user

    return responsible_user(client)


# ---------------------------------------------------------------- approving a document


def approval_step(task):
    if task is None or task.is_cancelled:
        return None
    steps = task.steps.filter(done_at__isnull=True)
    return (
        steps.filter(name__icontains="approv").first()
        or steps.filter(name__icontains="client").first()
    )


def item_document(item: PortalItem) -> Document | None:
    return Document.objects.live().filter(pk=item.object_id, client=item.client).first()


@transaction.atomic
def approve_document(item: PortalItem, user: User, *, typed_name: str, agreed: bool, ip, agent):
    """Same mechanism as signing: tick box, typed name, a record kept as a PDF page."""
    import datetime
    import hashlib

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils.html import escape

    from apps.comms import letters as pdf
    from apps.tasks import services as task_services

    typed_name = " ".join((typed_name or "").split())
    if not agreed:
        raise ValidationError("Tick the box to say you have read and approve this.")
    if len(typed_name) < 3:
        raise ValidationError("Type your full name.")
    item = PortalItem.objects.select_for_update().get(pk=item.pk)
    if item.kind != PortalItem.Kind.APPROVE_DOCUMENT or item.state != PortalItem.State.OPEN:
        raise ValidationError("This has already been dealt with.")
    document = item_document(item)
    if document is None:
        raise ValidationError("The document is no longer available.")
    with document.file.open("rb") as handle:
        fingerprint = hashlib.sha256(handle.read()).hexdigest()
    now = timezone.now()
    local, utc = timezone.localtime(now), now.astimezone(datetime.UTC)
    contact = getattr(user, "portal_contact", None)
    rows = [
        ("Approved by", typed_name),
        ("Email address", user.email),
        ("Document", document.title),
        ("Time (UK)", f"{local:%d/%m/%Y %H:%M:%S %Z}"),
        ("Time (UTC)", f"{utc:%d/%m/%Y %H:%M:%S} UTC"),
        ("IP address", ip or "not recorded"),
        ("Browser", agent or "not recorded"),
        ("Document fingerprint (SHA-256)", fingerprint),
    ]
    body = "".join(
        "<tr><th style='text-align:left;padding:4px 10px 4px 0;vertical-align:top'>"
        f"{escape(k)}</th>"
        f"<td style='word-break:break-all'>{escape(v)}</td></tr>"
        for k, v in rows
    )
    html = (
        f"<h1>Approval record</h1><p>This page records the approval of "
        f"“{escape(document.title)}” for {escape(item.client.name)}.</p><table>{body}</table>"
    )
    data = pdf.render_pdf(html, PracticeSettings.load(), on_date=local.date())
    upload = SimpleUploadedFile(
        f"Approval of {document.title}.pdf"[:200], data, content_type="application/pdf"
    )
    page = client_services.store_document(
        None, item.client, upload, category=Document.Category.CORRESPONDENCE
    )
    page.source = Document.Source.SYSTEM
    page.shared_with_portal = True
    page.save(update_fields=["source", "shared_with_portal", "updated_at"])
    events.record(
        user,
        "portal.document_approved",
        f"{typed_name} approved {document.title} for {item.client.name}.",
        client=item.client,
        target=document,
        actor_label=typed_name,
        fingerprint=fingerprint,
        approval_document_id=page.pk,
    )
    task = item.task
    step = approval_step(task)
    if step is not None:
        task_services.toggle_step(user, step, True)
    complete_item(item, contact, actor=user)
    owner = (task.owner if task else None) or client_services_owner(item.client)
    if owner is not None:
        link = (
            task_services.task_url(task)
            if task
            else reverse("clients:documents", args=[item.client.pk])
        )
        events.notify(
            owner, f"{typed_name} approved {document.title} for {item.client.name}.", link
        )
    return page
