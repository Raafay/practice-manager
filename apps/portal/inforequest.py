"""Asking a client for missing details: a secure no-login link, or a form sent by post.

Only the fields still empty on the record are asked for. Replies wait on the
InfoRequest until staff apply them, and land in Client requests with any files.
Tax references and codes are sealed (encrypted) in the stored answers and never
written to the activity log. Reminders go out after 7 and 14 days, through the
approval queue like every other message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps import events
from apps.clients.forms import ENCRYPTED_CLEANERS
from apps.clients.models import Client, Contact
from apps.core import actionlinks
from apps.core.fields import mask
from apps.core.models import ActionLink, PracticeSettings
from apps.core.siteurl import absolute

from . import requests as request_services
from .formspecs import seal, unseal
from .models import InfoRequest, Request

LINK_DAYS = 28
REMINDER_DAYS = (7, 14)
PURPOSE = ActionLink.Purpose.FORM


@dataclass(frozen=True)
class Ask:
    key: str
    label: str
    on: str  # "client" or "contact"
    attr: str
    input: str = "text"  # text, textarea, date, email, secret
    company_only: bool = False

    @property
    def secret(self) -> bool:
        return self.input == "secret"


ASKS = [
    Ask("email", "Email address", "contact", "email", "email"),
    Ask("phone", "Phone number", "contact", "mobile"),
    Ask("home_address", "Home address", "contact", "home_address", "textarea"),
    Ask("dob", "Date of birth", "contact", "date_of_birth", "date"),
    Ask("ni_number", "National Insurance number", "contact", "ni_number", "secret"),
    Ask(
        "personal_utr",
        "Personal UTR (Unique Taxpayer Reference)",
        "contact",
        "personal_utr",
        "secret",
    ),
    Ask(
        "ch_personal_code",
        "Companies House personal code",
        "contact",
        "ch_personal_code",
        "secret",
    ),
    Ask("company_utr", "Company UTR", "client", "company_utr", "secret", company_only=True),
    Ask(
        "ch_auth_code",
        "Companies House authentication code",
        "client",
        "ch_auth_code",
        "secret",
        company_only=True,
    ),
]
BY_KEY = {a.key: a for a in ASKS}


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def _target(ask: Ask, client: Client, contact: Contact):
    return client if ask.on == "client" else contact


def current(ask: Ask, client: Client, contact: Contact):
    value = getattr(_target(ask, client, contact), ask.attr)
    if ask.key == "phone" and not value:
        value = contact.phone
    return value


def applies(ask: Ask, client: Client) -> bool:
    return not ask.company_only or client.is_company


def missing(client: Client, contact: Contact) -> list[str]:
    """Keys of the fields still empty on the record for this client and person."""
    return [a.key for a in ASKS if applies(a, client) and not current(a, client, contact)]


def asks_for(info: InfoRequest) -> list[Ask]:
    return [BY_KEY[k] for k in info.fields if k in BY_KEY]


def still_missing(info: InfoRequest) -> list[Ask]:
    """The asked fields that are still empty now: the link shows only these."""
    return [a for a in asks_for(info) if not current(a, info.client, info.contact)]


def shown_answer(ask: Ask, value: str) -> str:
    value = unseal(value)
    return mask(value) if ask.secret and value else value


# ---------------------------------------------------------------- checking answers


def clean_value(ask: Ask, raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if ask.input == "date":
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise ValidationError(f"{ask.label}: enter a date such as 1980-04-30.") from None
        if day >= timezone.localdate() or day.year < 1900:
            raise ValidationError(f"{ask.label}: enter a date in the past.")
        return day.isoformat()
    if ask.input == "email":
        from django.core.validators import validate_email

        try:
            validate_email(value)
        except ValidationError:
            raise ValidationError(f"{ask.label}: enter a valid email address.") from None
        return value[:254]
    if ask.secret:
        value = re.sub(r"\s+", "", value).upper()
        pattern, message = ENCRYPTED_CLEANERS[ask.attr]
        if not pattern.match(value):
            raise ValidationError(message)
        return value
    return value[:2000]


def clean_answers(asks: list[Ask], data) -> dict:
    """Check the posted values. Returns {key: stored value}; secrets come back sealed."""
    errors, answers = [], {}
    for ask in asks:
        try:
            value = clean_value(ask, data.get(ask.key, ""))
        except ValidationError as error:
            errors.extend(error.messages)
            continue
        if value:
            answers[ask.key] = seal(value) if ask.secret else value
    if errors:
        raise ValidationError(errors)
    return answers


# ---------------------------------------------------------------- sending


def _message_html(info: InfoRequest, url: str, *, reminder: int = 0) -> tuple[str, str]:
    practice = PracticeSettings.load()
    items = "".join(f"<li>{escape(a.label)}</li>" for a in still_missing(info))
    opening = (
        "<p>A reminder: we are still waiting for a few details from you.</p>"
        if reminder
        else "<p>To finish setting up your records we need a few details from you.</p>"
    )
    expires = timezone.localtime(info.expires_at).strftime("%d/%m/%Y")
    html = (
        f"<p>Dear {escape(info.contact.first_name or info.contact.full_name)},</p>"
        + opening
        + f"<ul>{items}</ul>"
        + f'<p><a href="{escape(url)}">Fill in the secure form</a>. You do not need to sign in. '
        f"You can also upload a photo of your passport or driving licence and a recent proof "
        f"of address. The link works until {expires}.</p>"
        "<p>If you would rather reply by post, tell us and we will send a paper form.</p>"
        f"<p>{escape(practice.practice_name)}</p>"
    )
    subject = ("Reminder: " if reminder else "") + f"Details we need for {info.client.name}"
    return subject, html


def _queue_email(actor, info: InfoRequest, *, reminder: int = 0):
    from apps.comms import services as comms

    link, token = actionlinks.create(
        purpose=PURPOSE,
        contact=info.contact,
        client=info.client,
        object_id=info.pk,
        created_by=actor,
        expires_at=info.expires_at,
    )
    url = absolute(reverse("portal:info_form", args=[token]))
    subject, html = _message_html(info, url, reminder=reminder)
    return comms.create_message(
        info.client,
        created_by=actor,
        to=info.contact.email,
        subject=subject,
        body_html=html,
        contact=info.contact,
        reason=f"Information request {info.reference}"
        + (f", reminder {reminder}" if reminder else ""),
        duplicate_key=f"info-{info.pk}-{reminder}",
    )


@transaction.atomic
def create(actor, client: Client, contact: Contact, *, channel: str, fields=None) -> InfoRequest:
    if not client.client_contacts.filter(contact=contact).exists():
        raise ValidationError("That person is not linked to this client.")
    wanted = missing(client, contact)
    keys = [k for k in (fields or wanted) if k in wanted]
    if not keys:
        raise ValidationError("Nothing is missing for this person, so there is nothing to ask.")
    if channel == InfoRequest.Channel.EMAIL and not contact.email:
        raise ValidationError(f"{contact.full_name} has no email address. Send it by post.")
    now = timezone.now()
    info = InfoRequest.objects.create(
        client=client,
        contact=contact,
        channel=channel,
        fields=keys,
        created_by=actor,
        sent_at=now,
        expires_at=now + timedelta(days=LINK_DAYS),
    )
    if channel == InfoRequest.Channel.EMAIL:
        _queue_email(actor, info)
    labels = ", ".join(BY_KEY[k].label for k in keys)
    events.record(
        actor,
        "info_request.created",
        f"{who(actor)} asked {contact.full_name} for missing details "
        f"{'by email' if channel == 'email' else 'by post'}: {labels}.",
        client=client,
        target=info,
        channel=channel,
        fields=keys,
    )
    return info


def postal_pdf(info: InfoRequest) -> bytes:
    """The same questions on paper, with the practice's return address."""
    from apps.comms.letters import render_pdf

    practice = PracticeSettings.load()
    rows = "".join(
        f"<tr><th style='text-align:left;width:40%;padding:10px 6px'>{escape(a.label)}</th>"
        "<td style='border-bottom:1px solid #94a3b8;"
        f"height:{70 if a.input == 'textarea' else 30}px'></td></tr>"
        for a in still_missing(info)
    )
    body = (
        f"<h1>Details we need for {escape(info.client.name)}</h1>"
        f"<p>Dear {escape(info.contact.full_name)},</p>"
        "<p>Please fill in the details below and post this form back to us. You may enclose a "
        "copy of your passport or driving licence and a recent proof of address.</p>"
        f"<table style='width:100%;border-collapse:collapse'>{rows}</table>"
        f"<p style='margin-top:24px'><strong>Return to:</strong></p>"
        f"{linebreaks(escape(practice.practice_name + chr(10) + practice.address))}"
        f"<p style='color:#64748b'>Reference {info.reference}</p>"
    )
    return render_pdf(body, practice)


# ---------------------------------------------------------------- replies


def link_for(token: str) -> tuple[ActionLink, InfoRequest] | None:
    link = actionlinks.resolve(token, PURPOSE)
    if link is None:
        return None
    info = (
        InfoRequest.objects.filter(pk=link.object_id, client=link.client, contact=link.contact)
        .select_related("client", "contact")
        .first()
    )
    if info is None or info.state != InfoRequest.State.WAITING or link.used_at:
        return None
    return link, info


@transaction.atomic
def submit(link: ActionLink, info: InfoRequest, data, uploads=(), *, ip=None) -> InfoRequest:
    """The client's reply through the link. Files go to Client requests."""
    answers = clean_answers(still_missing(info), data)
    uploads = request_services.check_files(uploads, max_files=5)
    if not answers and not uploads:
        raise ValidationError("Fill in at least one detail or add a file.")
    now = timezone.now()
    labels = ", ".join(BY_KEY[k].label for k in answers) or "files only"
    req = request_services.create_request(
        channel=Request.Channel.FORM,
        client=info.client,
        contact=info.contact,
        sender_name=info.contact.full_name,
        sender_email=info.contact.email,
        subject=f"Details sent for {info.reference}",
        body=f"{info.contact.full_name} replied to information request {info.reference}.\n"
        f"Details given: {labels}.\nCheck and apply them on the information request.",
        uploads=uploads,
        ip=ip,
        actor_label=info.contact.full_name,
    )
    info.answers = answers
    info.state = InfoRequest.State.ANSWERED
    info.answered_at = now
    info.request = req
    info.save(update_fields=["answers", "state", "answered_at", "request", "updated_at"])
    link.used_at = now
    link.save(update_fields=["used_at", "updated_at"])
    events.record(
        None,
        "info_request.answered",
        f"{info.contact.full_name} sent details for {info.reference}: {labels}.",
        client=info.client,
        target=info,
        actor_label=info.contact.full_name,
        fields=list(answers),
    )
    return info


@transaction.atomic
def record_postal_reply(actor, info: InfoRequest, data) -> InfoRequest:
    """Staff type in the answers from a paper form that came back."""
    if not info.is_open:
        raise ValidationError("This request is closed.")
    answers = clean_answers(still_missing(info), data)
    if not answers:
        raise ValidationError("Type in at least one detail from the form.")
    info.answers = {**info.answers, **answers}
    info.state = InfoRequest.State.ANSWERED
    info.answered_at = timezone.now()
    info.save(update_fields=["answers", "state", "answered_at", "updated_at"])
    events.record(
        actor,
        "info_request.answered",
        f"{who(actor)} typed in the details returned by post for {info.reference}: "
        + ", ".join(BY_KEY[k].label for k in answers)
        + ".",
        client=info.client,
        target=info,
        fields=list(answers),
    )
    return info


@transaction.atomic
def apply(actor, info: InfoRequest, keys) -> list[str]:
    """Copy chosen answers onto the client and contact. Returns the labels applied."""
    if info.state != InfoRequest.State.ANSWERED:
        raise ValidationError("There is nothing to apply.")
    done = []
    for key in keys:
        ask = BY_KEY.get(key)
        if ask is None or key not in info.answers:
            continue
        value = unseal(info.answers[key])
        target = _target(ask, info.client, info.contact)
        setattr(target, ask.attr, date.fromisoformat(value) if ask.input == "date" else value)
        target.save()
        done.append(key)
    info.applied = sorted(set(info.applied) | set(done))
    # Answers are cleared once dealt with, so sealed values do not linger here.
    info.answers = {}
    info.state = InfoRequest.State.DONE
    info.closed_at, info.closed_by = timezone.now(), actor
    info.save(update_fields=["applied", "answers", "state", "closed_at", "closed_by", "updated_at"])
    labels = [BY_KEY[k].label for k in done]
    events.record(
        actor,
        "info_request.applied",
        f"{who(actor)} applied details from {info.reference}: "
        + (", ".join(labels) or "none")
        + ".",
        client=info.client,
        target=info,
        fields=done,
    )
    return labels


@transaction.atomic
def cancel(actor, info: InfoRequest) -> InfoRequest:
    if not info.is_open:
        raise ValidationError("This request is already closed.")
    actionlinks.cancel_for(PURPOSE, info.pk)
    info.state = InfoRequest.State.CANCELLED
    info.answers = {}
    info.closed_at, info.closed_by = timezone.now(), actor
    info.save(update_fields=["state", "answers", "closed_at", "closed_by", "updated_at"])
    events.record(
        actor,
        "info_request.cancelled",
        f"{who(actor)} cancelled information request {info.reference}.",
        client=info.client,
        target=info,
    )
    return info


# ---------------------------------------------------------------- reminders


def send_reminders(today: date | None = None) -> int:
    """After 7 and 14 days: queue a reminder (email) or tell the sender (post)."""
    now = timezone.now()
    count = 0
    waiting = InfoRequest.objects.filter(
        state=InfoRequest.State.WAITING, reminders_sent__lt=len(REMINDER_DAYS)
    ).select_related("client", "contact", "created_by")
    for info in waiting:
        due_days = REMINDER_DAYS[info.reminders_sent]
        if info.sent_at is None or now < info.sent_at + timedelta(days=due_days):
            continue
        if not still_missing(info):
            continue
        number = info.reminders_sent + 1
        if info.channel == InfoRequest.Channel.EMAIL and info.contact.email:
            if info.expires_at and info.expires_at <= now:
                continue
            _queue_email(None, info, reminder=number)
        else:
            people = [info.created_by] if info.created_by else []
            for user in people or request_services.staff_to_tell(info.client):
                if user is not None:
                    events.notify(
                        user,
                        f"No reply by post after {due_days} days to {info.reference} "
                        f"for {info.client.name}.",
                        reverse("portal:info_detail", args=[info.client.pk, info.pk]),
                        kind="request",
                    )
        info.reminders_sent = number
        info.save(update_fields=["reminders_sent", "updated_at"])
        events.record(
            None,
            "info_request.reminded",
            f"Reminder {number} for information request {info.reference}.",
            client=info.client,
            target=info,
        )
        count += 1
    return count
