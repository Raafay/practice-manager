"""Business rules for messages: building, approving, sending and logging them.

Nothing here reaches a client unless a QueuedMessage exists and is approved, or
its template is set to send automatically (security rule 7).
"""

import mimetypes
import re
from datetime import timedelta
from email.utils import formataddr

from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps import events
from apps.core.html import clean_html
from apps.core.models import PracticeSettings

from . import merge
from .models import Channel, MessageTemplate, QueuedMessage, split_addresses

NEVER_MESSAGE_STATUSES = ("former", "lost")


def who(user) -> str:
    return user.name if user is not None and getattr(user, "name", "") else "The system"


# ---------------------------------------------------------------- recipients


def skip_reason(client, *, automatic: bool) -> str:
    """Why a client must not get this message, or an empty string.

    Automatic messages are never sent to a former or lost client, or to one with
    "do not send automatic messages" on. Hand-written ones only get a warning
    (see `warning_for`), so they pass here.
    """
    if client.status in NEVER_MESSAGE_STATUSES:
        return f"The client is {client.get_status_display().lower()}."
    if automatic and client.no_auto_messages:
        return "The client is set to “do not send automatic messages”."
    if getattr(client, "archived_at", None) and automatic:
        return "The client is archived."
    return ""


def warning_for(client) -> str:
    """A warning shown before a hand-written message to such a client."""
    if client.status in NEVER_MESSAGE_STATUSES:
        return f"{client.name} is {client.get_status_display().lower()}. Are you sure?"
    if client.no_auto_messages:
        return f"{client.name} is set to “do not send automatic messages”."
    return ""


def reminder_recipients(client, *, main_only: bool = False):
    """The main contact, and contacts marked as receiving reminders. Only those with an address."""
    links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
    people = []
    for link in links:
        wanted = link.is_main or (link.receives_reminders and not main_only)
        if wanted and link.contact.email:
            people.append((link, link.contact))
    people.sort(key=lambda item: (not item[0].is_main, item[1].last_name))
    return [contact for _, contact in people]


def main_contact(client):
    link = (
        client.client_contacts.filter(is_main=True, resigned_on__isnull=True)
        .select_related("contact")
        .first()
    )
    return link.contact if link else None


# ---------------------------------------------------------------- building


def deadline_for_template(client, template):
    """The open deadline a template is about: the one its reminder schedule watches, else the
    client's nearest open one. None when the client has none."""
    open_deadlines = client.deadlines.filter(status="open").order_by("due_date")
    rules = list(template.schedules.exclude(rule="").values_list("rule", flat=True))
    if rules:
        found = open_deadlines.filter(rule__in=rules).first()
        if found:
            return found
    return open_deadlines.first()


def blanks_warning(template, deadline) -> str:
    """Words for the compose window when a template needs a deadline the client lacks."""
    uses = merge.find_fields(template.subject) + merge.find_fields(template.body)
    if deadline is None and any(name.startswith("deadline.") for name in uses):
        return (
            "This template mentions a deadline, but the client has no open one. "
            "Fill in the blanks by hand before sending."
        )
    return ""


def build_context(client, *, user=None, contact=None, deadline=None, task=None) -> merge.Context:
    return merge.Context(
        client=client,
        contact=contact or main_contact(client),
        user=user,
        deadline=deadline,
        task=task,
    )


def render_template(template: MessageTemplate, ctx: merge.Context):
    """Subject, HTML body, text body and a list of problems that block sending."""
    subject = merge.render_subject(template.subject, ctx)
    if template.channel == Channel.SMS:
        body = merge.render(template.body, ctx, html=False)
    else:
        body = merge.render(template.body, ctx, html=True)
    problems = list(dict.fromkeys(subject.problems() + body.problems()))
    return subject.text, body.html, body.text, problems


def check_addresses(*values: str) -> None:
    for value in values:
        for address in split_addresses(value):
            validate_email(address)


def create_message(
    client,
    *,
    created_by=None,
    template: MessageTemplate | None = None,
    to: str = "",
    cc: str = "",
    bcc: str = "",
    subject: str = "",
    body_html: str = "",
    body_text: str = "",
    channel: str = Channel.EMAIL,
    state: str = QueuedMessage.State.NEEDS_APPROVAL,
    reason: str = "",
    contact=None,
    task=None,
    deadline=None,
    duplicate_key: str | None = None,
    attachments=(),
    uses_signature: bool = True,
) -> QueuedMessage:
    """Make one queued message. Safe to call twice with the same duplicate_key."""
    if duplicate_key:
        existing = QueuedMessage.objects.filter(duplicate_key=duplicate_key).first()
        if existing is not None:
            return existing
    if channel == Channel.EMAIL:
        check_addresses(to, cc, bcc)
    body_html = clean_html(body_html) if body_html else ""
    if not body_text and body_html:
        body_text = merge.html_to_text(body_html)
    message = QueuedMessage.objects.create(
        client=client,
        channel=channel,
        template=template,
        contact=contact,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
        state=state,
        created_by=created_by,
        reason=reason[:300],
        task=task,
        deadline=deadline,
        duplicate_key=duplicate_key,
        uses_signature=uses_signature,
    )
    if attachments:
        message.attachments.set([d for d in attachments if not d.sensitive and not d.deleted_at])
    events.record(
        created_by,
        "message.queued",
        f"{who(created_by)} queued “{subject or 'a message'}” for {client.name}.",
        client=client,
        target=message,
        state=state,
        reason=reason,
    )
    return message


def has_unfilled_fields(message: QueuedMessage) -> list[str]:
    """Merge fields that were never filled in, or placeholders, still in the message."""
    found = merge.unknown_fields(message.subject, message.body_html, message.body_text)
    marked = "merge-unknown" in message.body_html or "not available yet]" in message.body_text
    hidden = "[fee hidden]" in message.body_html or "[fee hidden]" in message.body_text
    return (
        found
        + (["a link that is not available yet"] if marked else [])
        + (["a fee hidden from the person who wrote it"] if hidden else [])
    )


def shows_fees(message: QueuedMessage) -> bool:
    """True if the message came from a template that puts fees or invoices in it."""
    template = message.template
    return template is not None and (
        template.group == MessageTemplate.Group.FEES
        or merge.mentions_money(template.subject, template.body)
    )


# ---------------------------------------------------------------- approving


def approval_problems(message: QueuedMessage) -> list[str]:
    problems = []
    if message.channel == Channel.EMAIL and not message.to_list:
        problems.append("No email address.")
    if message.channel == Channel.SMS and not message.to.strip():
        problems.append("No mobile number.")
    if not message.subject and message.channel == Channel.EMAIL:
        problems.append("No subject.")
    if not (message.body_html or message.body_text).strip():
        problems.append("The message is empty.")
    for name in has_unfilled_fields(message):
        problems.append(f"Unfilled merge field: {name}.")
    reason = skip_reason(message.client, automatic=False)
    if reason:
        problems.append(reason)
    return problems


def can_approve(user, message: QueuedMessage) -> bool:
    if not user.can("comms.approve"):
        return False
    group = message.template.group if message.template else ""
    return not (group == MessageTemplate.Group.FEES and not user.can("comms.approve_fees"))


@transaction.atomic
def approve(message: QueuedMessage, user) -> QueuedMessage:
    if not can_approve(user, message):
        raise PermissionDenied
    message = QueuedMessage.objects.select_for_update().get(pk=message.pk)
    if message.state not in (
        QueuedMessage.State.DRAFT,
        QueuedMessage.State.NEEDS_APPROVAL,
        QueuedMessage.State.FAILED,
    ):
        raise ValidationError("This message cannot be approved in its current state.")
    problems = approval_problems(message)
    if problems:
        raise ValidationError(" ".join(problems))
    now = timezone.now()
    message.state = QueuedMessage.State.APPROVED
    message.approved_by = user
    message.approved_at = now
    message.send_after = message.send_after or now
    message.error = ""
    message.save()
    events.record(
        user,
        "message.approved",
        f"{who(user)} approved “{message.subject}” for {message.client.name}.",
        client=message.client,
        target=message,
    )
    return message


def cancel(message: QueuedMessage, user) -> QueuedMessage:
    if message.state in (QueuedMessage.State.SENT, QueuedMessage.State.SENDING):
        raise ValidationError("A message that has gone out cannot be cancelled.")
    message.state = QueuedMessage.State.CANCELLED
    message.save(update_fields=["state", "updated_at"])
    events.record(
        user,
        "message.cancelled",
        f"{who(user)} cancelled “{message.subject}” for {message.client.name}.",
        client=message.client,
        target=message,
    )
    return message


def update_draft(message: QueuedMessage, user, *, to, cc, bcc, subject, body_html) -> QueuedMessage:
    if not message.is_editable:
        raise ValidationError("This message can no longer be edited.")
    check_addresses(to, cc, bcc)
    message.to, message.cc, message.bcc = to, cc, bcc
    message.subject = subject
    message.body_html = clean_html(body_html)
    message.body_text = merge.html_to_text(message.body_html)
    if message.state == QueuedMessage.State.FAILED:
        message.state = QueuedMessage.State.NEEDS_APPROVAL
        message.error = ""
    message.save()
    events.record(
        user,
        "message.edited",
        f"{who(user)} edited “{subject}” for {message.client.name}.",
        client=message.client,
        target=message,
    )
    return message


def update_text(message: QueuedMessage, user, *, to: str, body_text: str) -> QueuedMessage:
    """Edit a text message, with the same rules as an email draft."""
    if not message.is_editable:
        raise ValidationError("This message can no longer be edited.")
    message.to = to
    message.body_text = body_text
    if message.state == QueuedMessage.State.FAILED:
        message.state = QueuedMessage.State.NEEDS_APPROVAL
        message.error = ""
    message.save()
    events.record(
        user,
        "message.edited",
        f"{who(user)} edited a text message for {message.client.name}.",
        client=message.client,
        target=message,
    )
    return message


def retry(message: QueuedMessage, user) -> QueuedMessage:
    """A failed message goes back to approved so the job picks it up again.

    The approval checks run again: the client may have left since it failed.
    """
    if message.state != QueuedMessage.State.FAILED:
        raise ValidationError("Only a failed message can be retried.")
    problems = approval_problems(message)
    if problems:
        raise ValidationError(problems)
    message.state = QueuedMessage.State.APPROVED
    message.approved_by = message.approved_by or user
    message.send_after = timezone.now()
    message.error = ""
    message.save()
    events.record(
        user,
        "message.retried",
        f"{who(user)} retried “{message.subject}” for {message.client.name}.",
        client=message.client,
        target=message,
    )
    return message


# ---------------------------------------------------------------- pause switch


def set_paused(user, paused: bool) -> PracticeSettings:
    if not user.can("comms.pause"):
        raise PermissionDenied
    practice = PracticeSettings.load()
    practice.comms_paused = paused
    practice.comms_paused_by = user if paused else None
    practice.comms_paused_at = timezone.now() if paused else None
    practice.save()
    events.record(
        user,
        "setting.changed",
        f"{who(user)} {'paused' if paused else 'resumed'} all automatic sending.",
        setting="comms_paused",
    )
    return practice


def is_paused() -> bool:
    return PracticeSettings.load().comms_paused


# ---------------------------------------------------------------- sending


def sending_address(practice: PracticeSettings | None = None) -> str:
    practice = practice or PracticeSettings.load()
    return practice.sending_address or practice.email or _bare(django_settings.DEFAULT_FROM_EMAIL)


def _bare(value: str) -> str:
    match = re.search(r"<([^>]+)>", value)
    return match.group(1) if match else value


def sender_for(message: QueuedMessage):
    """The person whose name the email carries: the approver, else the writer, else the manager."""
    return message.approved_by or message.created_by or message.client.manager


def build_email(message: QueuedMessage) -> EmailMultiAlternatives:
    practice = PracticeSettings.load()
    person = sender_for(message)
    display = f"{person.name} ({practice.practice_name})" if person else practice.practice_name
    from_header = formataddr((display, sending_address(practice)))
    reply_to = (
        [person.email] if person and person.email else ([practice.email] if practice.email else [])
    )
    bcc = split_addresses(message.bcc)
    if practice.bcc_practice:
        copy = practice.email or sending_address(practice)
        if copy and copy not in bcc:
            bcc.append(copy)
    text = message.body_text
    html = message.body_html
    wants_signature = message.uses_signature and person is not None and person.email_signature
    if wants_signature and person.email_signature not in text:
        text = f"{text}\n\n-- \n{person.email_signature}"
        sig_html = "<p>" + "<br>".join(_escape(person.email_signature).splitlines()) + "</p>"
        html = f"{html}{sig_html}" if html else ""
    email = EmailMultiAlternatives(
        subject=message.subject,
        body=text,
        from_email=from_header,
        to=message.to_list,
        cc=split_addresses(message.cc),
        bcc=bcc,
        reply_to=reply_to,
        connection=get_connection(),
    )
    if html:
        email.attach_alternative(html, "text/html")
    for document in message.attachments.all():
        if document.deleted_at or document.sensitive:
            continue
        with document.file.open("rb") as handle:
            content = handle.read()
        mimetype = document.content_type or mimetypes.guess_type(document.original_name)[0]
        email.attach(document.original_name, content, mimetype or "application/octet-stream")
    return email


def _escape(value: str) -> str:
    from django.utils.html import escape

    return escape(value)


def _claim(message: QueuedMessage) -> bool:
    """Move approved to sending in one conditional UPDATE, so two workers never both send."""
    return bool(
        QueuedMessage.objects.filter(pk=message.pk, state=QueuedMessage.State.APPROVED).update(
            state=QueuedMessage.State.SENDING
        )
    )


def send_one(message: QueuedMessage) -> QueuedMessage:
    """Send one approved message now. Records the result; never raises."""
    if not _claim(message):
        return message
    message.refresh_from_db()
    try:
        if message.channel == Channel.SMS:
            from .sms import get_backend

            backend = get_backend()
            if backend is None:
                raise RuntimeError("No text message provider is set up.")
            message.provider_message_id = str(backend.send(message.to, message.body_text) or "")
        else:
            if not message.to_list:
                raise ValueError("No email address.")
            email = build_email(message)
            email.send(fail_silently=False)
            status = getattr(email, "anymail_status", None)
            if status is not None and getattr(status, "message_id", None):
                message.provider_message_id = str(status.message_id)[:200]
    except Exception as error:  # noqa: BLE001 - any failure is recorded and shown
        message.state = QueuedMessage.State.FAILED
        message.error = str(error)[:500] or error.__class__.__name__
        message.save()
        events.record(
            None,
            "message.failed",
            f"Sending “{message.subject}” to {message.client.name} failed: {message.error}",
            client=message.client,
            target=message,
        )
        notice = message.approved_by or message.created_by
        if notice is not None:
            events.notify(
                notice,
                f"A message to {message.client.name} failed to send: {message.error}",
                "/messages/?state=failed",
            )
        return message
    message.state = QueuedMessage.State.SENT
    message.sent_at = timezone.now()
    message.error = ""
    message.save()
    events.record(
        message.approved_by,
        "message.sent",
        f"“{message.subject}” was sent to {', '.join(message.to_list) or message.to}.",
        client=message.client,
        target=message,
        channel=message.channel,
    )
    return message


def send_due(limit: int = 50) -> dict:
    """The job: send approved messages whose time has come, one at a time.

    While the pause switch is on, nothing leaves, approved or not.
    """
    if is_paused():
        return {"sent": 0, "failed": 0, "paused": True}
    now = timezone.now()
    due = QueuedMessage.objects.filter(
        state=QueuedMessage.State.APPROVED, send_after__lte=now
    ).order_by("send_after", "id")[:limit]
    sent = failed = 0
    for message in due:
        # A client who became former after approval is not written to.
        message.client.refresh_from_db()
        if message.client.status in NEVER_MESSAGE_STATUSES and not message.created_by_id:
            message.state = QueuedMessage.State.CANCELLED
            message.error = "Cancelled: the client is no longer current."
            message.save()
            continue
        result = send_one(message)
        if result.state == QueuedMessage.State.SENT:
            sent += 1
        elif result.state == QueuedMessage.State.FAILED:
            failed += 1
    return {"sent": sent, "failed": failed}


def send_now(message: QueuedMessage, user) -> QueuedMessage:
    """Approve and send straight away (compose window, 'Send now')."""
    approve(message, user)
    if is_paused():
        return message
    return send_one(message)


def recent_delivery_problems(days: int = 30) -> int:
    """Messages that bounced or were marked as spam in the last `days` days."""
    since = timezone.now() - timedelta(days=days)
    return QueuedMessage.objects.filter(
        delivery_state__in=["bounced", "complained"], updated_at__gte=since
    ).count()


def record_delivery(provider_message_id: str, delivery: str) -> int:
    """A delivery report from the provider. See apps/comms/delivery.py."""
    from .delivery import record

    return record(provider_message_id, delivery)


# ---------------------------------------------------------------- logging by hand


def log_email(actor, client, *, on_date, who_with: str, summary: str):
    from apps.clients.models import Note

    text = f"{on_date:%d/%m/%Y} · With {who_with}: {summary.strip()}"
    note = Note.objects.create(client=client, kind=Note.Kind.EMAIL, text=text, author=actor)
    events.record(
        actor,
        "email.logged",
        f"{who(actor)} logged an email with {who_with} for {client.name}.",
        client=client,
        target=note,
        note_id=note.pk,
        text=text[:1000],
    )
    return note


def pending_count() -> int:
    return QueuedMessage.objects.filter(state=QueuedMessage.State.NEEDS_APPROVAL).count()


def default_send_after():
    return timezone.now() + timedelta(seconds=0)
