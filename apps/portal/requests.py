"""Requests: the one inbox for everything clients ask for (spec 08 section 6)."""

from __future__ import annotations

import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.clients.documents import check_document_upload
from apps.clients.models import Client, Contact, Document

from .models import Request, RequestFile

MAX_FILES = 3
MAX_FILE_MB = 10
TOKEN_BYTES = 32


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


# ---------------------------------------------------------------- the request link


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def ensure_token(client: Client) -> str:
    """Every client has one request link. Created the first time it is needed."""
    if not client.request_token:
        client.request_token = new_token()
        client.save(update_fields=["request_token", "updated_at"])
    return client.request_token


def replace_token(actor, client: Client) -> str:
    client.request_token = new_token()
    client.save(update_fields=["request_token", "updated_at"])
    events.record(
        actor,
        "request.link_replaced",
        f"{who(actor)} replaced the request link for {client.name}. The old link no longer works.",
        client=client,
        target=client,
    )
    return client.request_token


def client_for_token(token: str) -> Client | None:
    """The client a link belongs to. A replaced, empty or unknown token gives None."""
    if not token or len(token) > 100:
        return None
    client = Client.objects.filter(request_token=token).first()
    if client is None or not secrets.compare_digest(client.request_token, token):
        return None
    if client.is_archived:
        return None
    return client


def link_path(client: Client) -> str:
    return reverse("portal:request_form", args=[ensure_token(client)])


# ---------------------------------------------------------------- files


def check_files(uploads, *, max_files: int = MAX_FILES, max_mb: int = MAX_FILE_MB) -> list:
    uploads = [u for u in uploads if u]
    if len(uploads) > max_files:
        raise ValidationError(f"Send up to {max_files} files at a time.")
    for upload in uploads:
        if upload.size > max_mb * 1024 * 1024:
            raise ValidationError(f"“{upload.name}” is larger than {max_mb} MB.")
        check_document_upload(upload)
    return uploads


def attach_files(request_obj: Request, uploads) -> list[RequestFile]:
    saved = []
    for upload in uploads:
        content_type = check_document_upload(upload)
        entry = RequestFile(
            request=request_obj,
            original_name=upload.name[:255],
            size=upload.size,
            content_type=content_type,
        )
        entry.file.save(upload.name, upload, save=False)
        entry.save()
        saved.append(entry)
    return saved


# ---------------------------------------------------------------- creating


def staff_to_tell(client: Client | None):
    from apps.accounts.models import User
    from apps.onboarding.services import responsible_user

    if client is not None:
        return [u for u in (client.manager, client.partner) if u and u.is_active] or [
            responsible_user(client)
        ]
    return list(User.objects.active_owners())


@transaction.atomic
def create_request(
    *,
    channel: str,
    client: Client | None = None,
    contact: Contact | None = None,
    sender_name: str = "",
    sender_email: str = "",
    sender_phone: str = "",
    subject: str = "",
    body: str = "",
    urgency: str = Request.Urgency.NORMAL,
    uploads=(),
    logged_by=None,
    ip: str | None = None,
    proposal_id: int | None = None,
    actor_label: str = "",
    notify: bool = True,
) -> Request:
    body = (body or "").strip()
    subject = " ".join((subject or "").split())
    if not body and not subject:
        raise ValidationError("Say what you need help with.")
    if not subject:
        subject = (body.splitlines()[0] if body else "")[:80]
    uploads = check_files(uploads, max_files=MAX_FILES if channel == Request.Channel.FORM else 10)
    request_obj = Request.objects.create(
        client=client,
        contact=contact,
        sender_name=sender_name.strip()[:150],
        sender_email=sender_email.strip()[:254],
        sender_phone=sender_phone.strip()[:40],
        channel=channel,
        subject=subject[:200],
        body=body[:10000],
        urgency=urgency if urgency in Request.Urgency.values else Request.Urgency.NORMAL,
        logged_by=logged_by,
        ip_address=ip or None,
        proposal_id=proposal_id,
    )
    attach_files(request_obj, uploads)
    name = request_obj.sender_name or (contact.full_name if contact else "Someone")
    events.record(
        logged_by,
        "request.received",
        f"{name} sent a request"
        + (f" for {client.name}" if client else "")
        + f" by {request_obj.get_channel_display().lower()}: {request_obj.subject}",
        client=client,
        target=request_obj,
        actor_label=actor_label or (name if logged_by is None else ""),
        channel=channel,
        urgency=request_obj.urgency,
    )
    if notify:
        link = reverse("portal:inbox_detail", args=[request_obj.pk])
        for user in staff_to_tell(client):
            if user is not None and user != logged_by:
                events.notify(
                    user,
                    f"New {'urgent ' if request_obj.urgency == 'urgent' else ''}request"
                    + (f" from {client.name}" if client else "")
                    + f": {request_obj.subject}",
                    link,
                    kind="request",
                )
    transaction.on_commit(lambda: acknowledge(request_obj))
    return request_obj


def acknowledge(request_obj: Request) -> None:
    """The optional acknowledgement email. Off unless the template is switched on."""
    from apps.comms import services as comms
    from apps.comms.models import MessageTemplate

    template = MessageTemplate.objects.filter(key="request_acknowledgement", active=True).first()
    if (
        template is None
        or request_obj.client is None
        or not request_obj.sender_email
        or request_obj.channel not in (Request.Channel.FORM, Request.Channel.PORTAL)
    ):
        return
    ctx = comms.build_context(request_obj.client, contact=request_obj.contact)
    ctx.extra["request_reference"] = request_obj.reference
    subject, html, text, problems = comms.render_template(template, ctx)
    if problems:
        return
    comms.create_message(
        request_obj.client,
        template=template,
        to=request_obj.sender_email,
        subject=subject.replace("{reference}", request_obj.reference),
        body_html=html.replace("{reference}", request_obj.reference),
        body_text=text.replace("{reference}", request_obj.reference),
    )


# ---------------------------------------------------------------- working a request


def _set_state(request_obj: Request, state: str, actor, verb: str, summary: str, **data) -> None:
    request_obj.state = state
    request_obj.save(update_fields=["state", "updated_at"])
    events.record(actor, verb, summary, client=request_obj.client, target=request_obj, **data)


def set_client(actor, request_obj: Request, client: Client | None) -> Request:
    request_obj.client = client
    request_obj.save(update_fields=["client", "updated_at"])
    events.record(
        actor,
        "request.client_set",
        f"{who(actor)} set the client of request {request_obj.reference} to "
        f"{client.name if client else 'general'}.",
        client=client,
        target=request_obj,
    )
    return request_obj


def close(actor, request_obj: Request, note: str) -> Request:
    note = (note or "").strip()
    if not note:
        raise ValidationError("Write a short closing note.")
    request_obj.closing_note = note[:500]
    request_obj.closed_at = timezone.now()
    request_obj.closed_by = actor
    _set_state(
        request_obj,
        Request.State.CLOSED,
        actor,
        "request.closed",
        f"{who(actor)} closed request {request_obj.reference}: {note[:120]}",
    )
    request_obj.save(update_fields=["closing_note", "closed_at", "closed_by", "updated_at"])
    return request_obj


def mark_spam(actor, request_obj: Request) -> Request:
    request_obj.closed_at = timezone.now()
    request_obj.closed_by = actor
    _set_state(
        request_obj,
        Request.State.SPAM,
        actor,
        "request.spam",
        f"{who(actor)} marked request {request_obj.reference} as spam.",
    )
    request_obj.save(update_fields=["closed_at", "closed_by", "updated_at"])
    return request_obj


def mark_answered(actor, request_obj: Request) -> Request:
    if request_obj.state in (Request.State.NEW, Request.State.IN_PROGRESS):
        _set_state(
            request_obj,
            Request.State.ANSWERED,
            actor,
            "request.answered",
            f"{who(actor)} replied to request {request_obj.reference}.",
        )
    return request_obj


def reopen(actor, request_obj: Request) -> Request:
    request_obj.closed_at = None
    request_obj.closed_by = None
    request_obj.closing_note = ""
    _set_state(
        request_obj,
        Request.State.IN_PROGRESS if request_obj.task_id else Request.State.NEW,
        actor,
        "request.reopened",
        f"{who(actor)} reopened request {request_obj.reference}.",
    )
    request_obj.save(update_fields=["closed_at", "closed_by", "closing_note", "updated_at"])
    return request_obj


def file_as_documents(actor, request_obj: Request, task=None) -> list[Document]:
    """Carry attachments over as documents on the client (and the task, when there is one)."""
    from apps.tasks import services as task_services

    client = request_obj.client
    documents = []
    if client is None:
        return documents
    for entry in request_obj.files.filter(document__isnull=True):
        document = Document(
            client=client,
            contact=request_obj.contact,
            category=Document.Category.CORRESPONDENCE,
            title=entry.original_name.rsplit(".", 1)[0][:200],
            original_name=entry.original_name,
            size=entry.size,
            content_type=entry.content_type,
            uploaded_by=actor,
            source=Document.Source.REQUEST,
        )
        with entry.file.open("rb") as handle:
            from django.core.files.base import ContentFile

            document.file.save(entry.original_name, ContentFile(handle.read()), save=False)
        document.save()
        entry.document = document
        entry.save(update_fields=["document", "updated_at"])
        events.record(
            actor,
            "document.uploaded",
            f"{who(actor)} filed {document.title} from request {request_obj.reference} "
            f"under {client.name}.",
            client=client,
            target=document,
            source="request",
        )
        if task is not None:
            task_services.attach_document(actor, task, document)
        documents.append(document)
    return documents


@transaction.atomic
def convert_to_task(
    actor, request_obj: Request, *, category, owner, target_date=None, title: str = ""
):
    """Make a task from the request. Attachments carry over as documents."""
    from apps.core.dates import add_working_days
    from apps.tasks import services as task_services
    from apps.tasks.models import Task, TaskKind

    if request_obj.client is None:
        raise ValidationError("Choose a client first, or log it as a general task.")
    if request_obj.task_id:
        raise ValidationError("This request already has a task.")
    target = target_date or add_working_days(timezone.localdate(), 3)
    description = (
        f"<p>{_para(request_obj.body)}</p>"
        f"<p>Request {request_obj.reference} from {_esc(request_obj.sender_name or 'a client')}"
        f" by {_esc(request_obj.get_channel_display().lower())}.</p>"
    )
    task = task_services.create_task(
        actor,
        title=title or request_obj.subject or f"Request {request_obj.reference}",
        client=request_obj.client,
        kind=TaskKind.REQUEST,
        category=category,
        owner=owner,
        target_date=target,
        description=description,
        source=Task.Source.REQUEST,
        contact=request_obj.contact,
        priority=Task.Priority.HIGH
        if request_obj.urgency == Request.Urgency.URGENT
        else Task.Priority.NORMAL,
    )
    request_obj.task = task
    _set_state(
        request_obj,
        Request.State.IN_PROGRESS,
        actor,
        "request.converted",
        f"{who(actor)} made task “{task.title}” from request {request_obj.reference}.",
        task_id=task.pk,
    )
    request_obj.save(update_fields=["task", "updated_at"])
    file_as_documents(actor, request_obj, task)
    return task


def link_to_task(actor, request_obj: Request, task) -> Request:
    if request_obj.task_id:
        raise ValidationError("This request already has a task.")
    if request_obj.client_id and task.client_id and request_obj.client_id != task.client_id:
        raise ValidationError("That task belongs to a different client.")
    if request_obj.client is None and task.client_id:
        request_obj.client = task.client
    request_obj.task = task
    _set_state(
        request_obj,
        Request.State.IN_PROGRESS,
        actor,
        "request.linked",
        f"{who(actor)} linked request {request_obj.reference} to task “{task.title}”.",
        task_id=task.pk,
    )
    request_obj.save(update_fields=["task", "client", "updated_at"])
    file_as_documents(actor, request_obj, task)
    return request_obj


def close_for_done_task(task) -> int:
    """A request closes by itself when its task is done."""
    count = 0
    for request_obj in Request.objects.filter(task=task, state=Request.State.IN_PROGRESS):
        request_obj.state = Request.State.CLOSED
        request_obj.closing_note = "The task was completed."
        request_obj.closed_at = timezone.now()
        request_obj.save(update_fields=["state", "closing_note", "closed_at", "updated_at"])
        events.record(
            None,
            "request.closed",
            f"Request {request_obj.reference} was closed because its task was completed.",
            client=request_obj.client,
            target=request_obj,
        )
        count += 1
    return count


def _esc(value: str) -> str:
    from django.utils.html import escape

    return escape(value)


def _para(value: str) -> str:
    return "<br>".join(_esc(line) for line in (value or "").splitlines())


def new_count() -> int:
    return Request.objects.new().count()
