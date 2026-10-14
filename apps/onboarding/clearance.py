"""Professional clearance: asking the previous accountant to hand over (spec 06 section 7)."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.utils.html import escape

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, Document
from apps.comms import letters as pdf
from apps.comms import services as comms
from apps.comms.models import MessageTemplate
from apps.core.models import PracticeSettings

from .models import ClearanceRequest

CHASE_AFTER_DAYS = 14


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def _list_html(labels: list[str]) -> str:
    if not labels:
        return ""
    items = "".join(f"<li>{escape(label)}</li>" for label in labels)
    return f"<p>We would be grateful for:</p><ul>{items}</ul>"


def _render(template_key: str, client: Client, actor, labels: list[str]):
    template = MessageTemplate.objects.get(key=template_key)
    ctx = comms.build_context(client, user=actor)
    subject, html, _, problems = comms.render_template(template, ctx)
    if problems:
        raise ValidationError(" ".join(problems))
    return template, subject, html + _list_html(labels)


def start(actor, client: Client, *, accountant_name, email, firm="", asked_for=(), notes=""):
    """Record the request, make the PDF copy, and queue the email for approval."""
    labels_by_key = dict(ClearanceRequest.ITEMS)
    asked = [k for k in asked_for if k in labels_by_key]
    labels = [labels_by_key[k] for k in asked]
    request = ClearanceRequest.objects.create(
        client=client,
        accountant_name=accountant_name.strip(),
        firm=firm.strip(),
        email=email,
        asked_for=asked,
        notes=notes,
        sent_on=timezone.localdate(),
        created_by=actor,
    )
    # The PDF copy, on the practice letterhead, kept in Documents.
    letter_template, letter_subject, letter_html = _render(
        "clearance_letter", client, actor, labels
    )
    data = pdf.render_pdf(
        f"<h1>{escape(letter_subject)}</h1>{letter_html}", PracticeSettings.load()
    )
    document = client_services.store_document(
        actor,
        client,
        SimpleUploadedFile(
            f"Professional clearance request {timezone.localdate():%Y-%m-%d}.pdf",
            data,
            content_type="application/pdf",
        ),
        category=Document.Category.CORRESPONDENCE,
    )
    template, subject, html = _render("clearance_request", client, actor, labels)
    message = comms.create_message(
        client,
        created_by=actor,
        template=template,
        to=email,
        subject=subject,
        body_html=html,
        reason="Professional clearance request",
        attachments=[document],
    )
    request.letter_document = document
    request.message = message
    request.save()
    events.record(
        actor,
        "clearance.requested",
        f"{who(actor)} asked {accountant_name} for professional clearance for {client.name}. "
        "The email waits in Queued.",
        client=client,
        target=request,
    )
    return request


def chase_due(request: ClearanceRequest, today: date | None = None) -> bool:
    today = today or timezone.localdate()
    if request.reply_received_on or request.chased_on or request.sent_on is None:
        return False
    return today >= request.sent_on + timedelta(days=CHASE_AFTER_DAYS)


def chase(actor, request: ClearanceRequest) -> ClearanceRequest:
    if request.reply_received_on:
        raise ValidationError("A reply has already arrived.")
    if request.chased_on:
        raise ValidationError("This request has already been chased.")
    labels_by_key = dict(ClearanceRequest.ITEMS)
    labels = [labels_by_key[k] for k in request.asked_for if k in labels_by_key]
    template, subject, html = _render("clearance_chase", request.client, actor, labels)
    request.chase_message = comms.create_message(
        request.client,
        created_by=actor,
        template=template,
        to=request.email,
        subject=subject,
        body_html=html,
        reason="Professional clearance chase",
    )
    request.chased_on = timezone.localdate()
    request.save()
    events.record(
        actor,
        "clearance.chased",
        f"{who(actor)} queued a chase to {request.accountant_name} for {request.client.name}.",
        client=request.client,
        target=request,
    )
    return request


def update(actor, request: ClearanceRequest, *, received, reply_received_on, notes):
    valid = {k for k, _ in ClearanceRequest.ITEMS}
    request.received = [k for k in received if k in valid]
    request.reply_received_on = reply_received_on
    request.notes = notes
    request.save()
    events.record(
        actor,
        "clearance.updated",
        f"{who(actor)} updated the clearance request for {request.client.name}"
        + (f": reply received {reply_received_on:%d/%m/%Y}." if reply_received_on else "."),
        client=request.client,
        target=request,
    )
    return request
