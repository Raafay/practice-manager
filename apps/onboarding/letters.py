"""Engagement letters: prepare, send through the queue, sign on screen (spec 06 section 2)."""

from __future__ import annotations

import datetime
import hashlib
from datetime import date

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, linebreaks

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, Contact, Document
from apps.comms import letters as pdf
from apps.comms import merge
from apps.comms import services as comms
from apps.comms.models import MessageTemplate
from apps.core import actionlinks
from apps.core.dates import add_months
from apps.core.html import clean_html
from apps.core.models import ActionLink, PracticeSettings
from apps.core.money import format_money
from apps.core.siteurl import absolute
from apps.services.models import ClientService

from . import services as onboarding
from .models import EngagementLetter, LetterPart

REVIEW_MONTHS = 12
LINK_DAYS = 14
State = EngagementLetter.State


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def _part(key: str) -> str:
    part = LetterPart.objects.filter(key=key).first()
    return part.body if part else ""


def letter_services(client: Client):
    return client.client_services.exclude(state=ClientService.State.ENDED).select_related("service")


def frozen_services(client: Client) -> list[dict]:
    return [
        {
            "service": cs.service.name,
            "code": cs.service.code,
            "fee": str(cs.fee_amount) if cs.fee_amount is not None else "",
            "frequency": cs.fee_frequency,
            "frequency_label": cs.get_fee_frequency_display().lower(),
            "starts_on": cs.starts_on.isoformat() if cs.starts_on else "",
        }
        for cs in letter_services(client)
    ]


def signer_choices(client: Client):
    """People who can sign: contacts on the client with an email address."""
    links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
    return [link.contact for link in links if link.contact.email]


def default_signer(client: Client) -> Contact | None:
    choices = signer_choices(client)
    signers = [
        c for c in choices if client.client_contacts.filter(contact=c, can_sign=True).exists()
    ]
    main = client.main_contact
    for contact in [main, *signers, *choices]:
        if contact is not None and contact.email:
            return contact
    return None


def uses_starter_wording() -> bool:
    return LetterPart.objects.filter(starter=True).exists()


def build_body(client: Client, contact: Contact | None, user, rows: list[dict]) -> str:
    """The covering letter, a schedule per service, terms and privacy notice, fields filled in."""
    ctx = comms.build_context(client, user=user, contact=contact)
    html = [merge.render(_part("covering"), ctx).html]
    if rows:
        html.append("<h2>Services and fees</h2>")
    for number, row in enumerate(rows, start=1):
        service = ClientService.objects.filter(client=client, service__code=row["code"]).first()
        text = (service.service.schedule_text if service else "").strip()
        schedule = (
            merge.render(str(linebreaks(escape(text))), ctx).html
            if text
            else (f"<p>We will provide {escape(row['service'].lower())} as agreed with you.</p>")
        )
        fee = ""
        if row["fee"]:
            from decimal import Decimal

            fee = (
                f"<p><strong>Fee:</strong> {escape(format_money(Decimal(row['fee'])))}"
                + ("" if row["frequency"] == "one_off" else f" {escape(row['frequency_label'])}")
                + (" (one-off)" if row["frequency"] == "one_off" else "")
                + " plus VAT if applicable.</p>"
            )
        html.append(f"<h3>Schedule {number}: {escape(row['service'])}</h3>{schedule}{fee}")
    html.append(merge.render(_part("terms"), ctx).html)
    html.append(merge.render(_part("privacy"), ctx).html)
    return clean_html("".join(html))


@transaction.atomic
def prepare_letter(actor, client: Client, signer: Contact | None = None) -> EngagementLetter:
    signer = signer or default_signer(client)
    if signer is None:
        raise ValidationError(
            "No one at this client has an email address to sign. Add a contact with one first."
        )
    rows = frozen_services(client)
    version = client.engagement_letters.order_by("-version").first() or None
    version = version.version + 1 if version else 1
    # Any earlier draft is superseded.
    client.engagement_letters.filter(state=State.DRAFT).update(state=State.CANCELLED)
    letter = EngagementLetter.objects.create(
        client=client,
        version=version,
        services=rows,
        body_html=build_body(client, signer, actor, rows),
        signer=signer,
        prepared_by=actor,
    )
    events.record(
        actor,
        "letter.prepared",
        f"{who(actor)} prepared engagement letter version {version} for {client.name}.",
        client=client,
        target=letter,
    )
    return letter


def save_draft(
    actor, letter: EngagementLetter, *, body_html: str, signer: Contact
) -> EngagementLetter:
    if not letter.is_editable:
        raise ValidationError("Only a draft letter can be edited.")
    if not signer.email:
        raise ValidationError(f"{signer.full_name} has no email address.")
    letter.body_html = clean_html(body_html)
    letter.signer = signer
    letter.save()
    events.record(
        actor,
        "letter.edited",
        f"{who(actor)} edited engagement letter version {letter.version} for {letter.client.name}.",
        client=letter.client,
        target=letter,
    )
    return letter


def blocking_problems(letter: EngagementLetter) -> list[str]:
    problems = []
    if letter.signer is None or not letter.signer.email:
        problems.append("The signer has no email address.")
    for name in merge.unknown_fields(letter.body_html):
        problems.append(f"Unknown merge field {{{{ {name} }}}}.")
    if "merge-unknown" in letter.body_html:
        problems.append("The letter still has an unfilled merge field.")
    if not letter.services:
        problems.append("The client has no services to put in the letter.")
    return problems


def _store_pdf(actor, client, name: str, data: bytes) -> Document:
    upload = SimpleUploadedFile(name, data, content_type="application/pdf")
    return client_services.store_document(
        actor, client, upload, category=Document.Category.ENGAGEMENT
    )


def sign_url(token: str) -> str:
    return absolute(reverse("onboarding:sign", args=[token]))


@transaction.atomic
def send_letter(actor, letter: EngagementLetter) -> EngagementLetter:
    """Freeze the letter, make the PDF, and queue the email with the signing link."""
    letter = EngagementLetter.objects.select_for_update().get(pk=letter.pk)
    if letter.state != State.DRAFT:
        raise ValidationError("This letter has already been sent.")
    problems = blocking_problems(letter)
    if problems:
        raise ValidationError(" ".join(problems))
    client, practice = letter.client, PracticeSettings.load()
    sent_on = timezone.localdate()
    data = pdf.render_pdf(
        f"<h1>Engagement letter</h1>{letter.body_html}", practice, on_date=sent_on
    )
    document = _store_pdf(
        actor, client, f"Engagement letter v{letter.version} (unsigned).pdf", data
    )
    link, token = actionlinks.create(
        purpose=ActionLink.Purpose.SIGN_LETTER,
        contact=letter.signer,
        client=client,
        object_id=letter.pk,
        created_by=actor,
        days=LINK_DAYS,
    )
    template = MessageTemplate.objects.get(key="engagement_letter_send")
    ctx = comms.build_context(client, user=actor, contact=letter.signer)
    ctx.extra["sign_link"] = sign_url(token)
    subject, html, text, template_problems = comms.render_template(template, ctx)
    if template_problems:
        raise ValidationError(" ".join(template_problems))
    message = comms.create_message(
        client,
        created_by=actor,
        template=template,
        to=letter.signer.email,
        subject=subject,
        body_html=html,
        body_text=text,
        contact=letter.signer,
        reason=f"Engagement letter version {letter.version}",
    )
    letter.unsigned_document = document
    letter.fingerprint = hashlib.sha256(data).hexdigest()
    letter.message = message
    letter.state = State.SENT
    letter.sent_at = timezone.now()
    letter.save()
    events.record(
        actor,
        "letter.sent",
        f"{who(actor)} sent engagement letter version {letter.version} to "
        f"{letter.signer.full_name} for {client.name}. The email waits in Queued.",
        client=client,
        target=letter,
        fingerprint=letter.fingerprint,
    )
    return letter


def cancel_letter(actor, letter: EngagementLetter) -> EngagementLetter:
    if letter.state in (State.SIGNED, State.REPLACED, State.CANCELLED):
        raise ValidationError("This letter cannot be cancelled.")
    letter.state = State.CANCELLED
    letter.save(update_fields=["state", "updated_at"])
    actionlinks.cancel_for(ActionLink.Purpose.SIGN_LETTER, letter.pk)
    events.record(
        actor,
        "letter.cancelled",
        f"{who(actor)} cancelled engagement letter version {letter.version} for "
        f"{letter.client.name}.",
        client=letter.client,
        target=letter,
    )
    return letter


def cancel_signing_link(actor, letter: EngagementLetter) -> int:
    count = actionlinks.cancel_for(ActionLink.Purpose.SIGN_LETTER, letter.pk)
    if count:
        events.record(
            actor,
            "letter.link_cancelled",
            f"{who(actor)} cancelled the signing link for engagement letter version "
            f"{letter.version} for {letter.client.name}.",
            client=letter.client,
            target=letter,
        )
    return count


def note_viewed(letter: EngagementLetter, link: ActionLink) -> None:
    """The page was opened. Opening many times is fine."""
    now = timezone.now()
    if link.first_opened_at is None:
        link.first_opened_at = now
        link.save(update_fields=["first_opened_at", "updated_at"])
    if letter.state == State.SENT:
        letter.state = State.VIEWED
        letter.viewed_at = now
        letter.save(update_fields=["state", "viewed_at", "updated_at"])
        events.record(
            None,
            "letter.viewed",
            f"{letter.signer} opened engagement letter version {letter.version} for "
            f"{letter.client.name}.",
            client=letter.client,
            target=letter,
            actor_label=str(letter.signer),
        )


def _signature_page(letter, typed_name, signer_email, when, ip, agent) -> str:
    local = timezone.localtime(when)
    utc = when.astimezone(datetime.UTC)
    rows = [
        ("Signed by", typed_name),
        ("Email address", signer_email),
        ("Time (UK)", f"{local:%d/%m/%Y %H:%M:%S %Z}"),
        ("Time (UTC)", f"{utc:%d/%m/%Y %H:%M:%S} UTC"),
        ("IP address", ip or "not recorded"),
        ("Browser", agent or "not recorded"),
        ("Letter", f"Engagement letter version {letter.version}"),
        ("Document fingerprint (SHA-256 of the unsigned PDF)", letter.fingerprint),
    ]
    body = "".join(
        f"<tr><th style='text-align:left;padding:4px 10px 4px 0;vertical-align:top'>"
        f"{escape(k)}</th><td style='word-break:break-all'>{escape(v)}</td></tr>"
        for k, v in rows
    )
    return (
        "<div style='page-break-before: always'><h1>Signature record</h1>"
        "<p>This page records the electronic signature of the engagement letter above.</p>"
        f"<table>{body}</table></div>"
    )


def sign_letter(
    link: ActionLink, *, typed_name: str, agreed: bool, ip: str | None, agent: str
) -> EngagementLetter:
    """Sign once. A second attempt, an expired link or a cancelled link all fail."""
    typed_name = " ".join((typed_name or "").split())
    if not agreed:
        raise ValidationError("Tick the box to say you have read and agree to the letter.")
    if len(typed_name) < 3:
        raise ValidationError("Type your full name.")
    with transaction.atomic():
        link = ActionLink.objects.select_for_update().get(pk=link.pk)
        if link.used_at is not None:
            raise ValidationError("This letter has already been signed.")
        if link.cancelled_at or link.expires_at <= timezone.now():
            raise ValidationError("This link is no longer valid.")
        letter = EngagementLetter.objects.select_for_update().get(pk=link.object_id)
        if letter.state not in (State.SENT, State.VIEWED):
            raise ValidationError("This letter can no longer be signed.")
        now = timezone.now()
        client, practice = letter.client, PracticeSettings.load()
        data = pdf.render_pdf(
            f"<h1>Engagement letter</h1>{letter.body_html}"
            + _signature_page(letter, typed_name, link.contact.email, now, ip, agent),
            practice,
            on_date=timezone.localtime(letter.sent_at).date(),
        )
        document = _store_pdf(
            None, client, f"Engagement letter v{letter.version} (signed).pdf", data
        )
        letter.signed_document = document
        letter.state = State.SIGNED
        letter.signed_at = now
        letter.signer = link.contact
        letter.typed_name = typed_name[:200]
        letter.signer_email = link.contact.email
        letter.ip_address = ip
        letter.user_agent = (agent or "")[:300]
        letter.review_due = add_months(timezone.localtime(now).date(), REVIEW_MONTHS)
        letter.save()
        link.used_at = now
        link.save(update_fields=["used_at", "updated_at"])
        client.engagement_letters.filter(state=State.SIGNED).exclude(pk=letter.pk).update(
            state=State.REPLACED
        )
        events.record(
            None,
            "letter.signed",
            f"{typed_name} signed engagement letter version {letter.version} for {client.name}.",
            client=client,
            target=letter,
            actor_label=typed_name,
            fingerprint=letter.fingerprint,
        )
        onboarding.tick(
            client,
            "engagement_letter_signed",
            note=f"Signed by {typed_name} on {timezone.localtime(now):%d/%m/%Y}.",
            auto=True,
        )
    _after_signing(letter)
    return letter


def _after_signing(letter: EngagementLetter) -> None:
    """Email the client a copy and tell staff. The copy waits in the queue."""
    client = letter.client
    template = MessageTemplate.objects.filter(key="engagement_letter_signed").first()
    if template is not None and letter.signer_email:
        ctx = comms.build_context(client, user=letter.prepared_by, contact=letter.signer)
        subject, html, text, problems = comms.render_template(template, ctx)
        if not problems:
            comms.create_message(
                client,
                created_by=letter.prepared_by,
                template=template,
                to=letter.signer_email,
                subject=subject,
                body_html=html,
                body_text=text,
                contact=letter.signer,
                reason=f"Signed copy of engagement letter version {letter.version}",
                attachments=[letter.signed_document],
                duplicate_key=f"letter-signed-{letter.pk}",
            )
    onboarding.notify_staff(
        client,
        f"{letter.typed_name} signed the engagement letter for {client.name}.",
        reverse("onboarding:engagement", args=[client.pk]),
        letter.prepared_by,
    )


def services_changed_since_signed(client: Client) -> bool:
    """True if the services or fees differ from the latest signed letter."""
    latest = client.engagement_letters.filter(state=State.SIGNED).first()
    if latest is None:
        return False

    def key(rows):
        return sorted((r["code"], r["fee"], r["frequency"]) for r in rows)

    return key(latest.services) != key(frozen_services(client))


def due_for_review(today: date | None = None):
    today = today or timezone.localdate()
    from datetime import timedelta

    return EngagementLetter.objects.filter(
        state=State.SIGNED, review_due__lte=today + timedelta(days=30), review_task_made=False
    ).select_related("client")
