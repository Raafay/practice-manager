"""Proposals: build from services, send through the queue, accept online (spec 05 section 4)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, Contact, Document, Note
from apps.comms import letters as pdf
from apps.comms import merge
from apps.comms import services as comms
from apps.comms.models import MessageTemplate
from apps.core import actionlinks
from apps.core.html import clean_html
from apps.core.models import ActionLink, PracticeSettings
from apps.core.money import format_money, to_pounds
from apps.core.siteurl import absolute
from apps.services.fees import monthly_equivalent

from . import services as pipeline
from .models import PipelineSettings, PipelineStage, Proposal, ProspectDetails

State = Proposal.State
LIVE_STATES = (State.DRAFT, State.SENT, State.VIEWED)

# The compose window shows the proposal link as this address; sending swaps in the real one.
LINK_PLACEHOLDER = "https://proposal.invalid/link"

PER = {
    "monthly": "per month",
    "quarterly": "per quarter",
    "annual": "per year",
    "one_off": "one-off",
}


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


# ---------------------------------------------------------------- lines and totals


def build_lines(client: Client) -> list[dict]:
    """A frozen copy of each proposed service: name, description, fee, frequency."""
    return [
        {
            "service": row.service.name,
            "code": row.service.code,
            "description": row.service.description,
            "fee": str(row.fee_amount) if row.fee_amount is not None else "",
            "frequency": row.fee_frequency,
        }
        for row in pipeline.proposed_services(client)
    ]


def line_fee(line: dict) -> Decimal | None:
    return Decimal(line["fee"]) if line.get("fee") not in (None, "") else None


def monthly_total(lines: list[dict]) -> Decimal:
    """Each recurring service becomes a month, rounded, then added. One-offs are kept apart."""
    total = Decimal("0.00")
    for line in lines:
        fee = line_fee(line)
        if fee is not None and line["frequency"] != "one_off":
            total += monthly_equivalent(fee, line["frequency"]) or Decimal("0.00")
    return total


def one_off_total(lines: list[dict]) -> Decimal:
    return sum(
        (line_fee(line) or Decimal("0.00") for line in lines if line["frequency"] == "one_off"),
        Decimal("0.00"),
    )


def current_vat_rate() -> Decimal | None:
    practice = PracticeSettings.load()
    return Decimal(practice.vat_rate) if practice.vat_registered else None


def with_vat(amount: Decimal, rate: Decimal) -> Decimal:
    return to_pounds(Decimal(amount) * (Decimal(1) + Decimal(rate) / Decimal(100)))


def money(amount: Decimal | None, proposal: Proposal) -> str:
    """An amount as the proposal shows it, following the VAT switches.

    Fees are stored without VAT. "Including VAT" multiplies by one plus the rate and applies only
    if the practice is VAT registered. "+VAT" wording follows amounts shown without VAT.
    """
    if amount is None:
        return ""
    rate = proposal.vat_rate
    if rate is not None and proposal.show_inc_vat:
        return f"{format_money(with_vat(amount, rate))} inc. VAT"
    text = format_money(amount)
    if rate is not None and proposal.show_vat_text:
        text += " +VAT"
    return text


def view_model(proposal: Proposal) -> dict:
    """Everything the page, the PDF and the email show, worked out once."""
    recurring, one_offs = [], []
    for line in proposal.lines:
        fee = line_fee(line)
        row = {
            "service": line["service"],
            "description": line.get("description", ""),
            "fee_text": f"{money(fee, proposal)} {PER[line['frequency']]}"
            if fee is not None
            else "",
            "frequency": line["frequency"],
        }
        (one_offs if line["frequency"] == "one_off" else recurring).append(row)
    one_off = one_off_total(proposal.lines)
    return {
        "proposal": proposal,
        "recurring": recurring,
        "one_offs": one_offs,
        "show_breakdown": proposal.show_breakdown,
        "monthly_text": money(proposal.monthly_total, proposal) if recurring else "",
        "one_off_text": money(one_off, proposal) if one_offs else "",
        "setup_text": money(proposal.setup_fee, proposal) if proposal.setup_fee else "",
        "has_charges": bool(recurring or one_offs or proposal.setup_fee),
    }


def summary_block(proposal: Proposal) -> tuple[str, str]:
    """The services and charges for the email, as (html, text)."""
    vm = view_model(proposal)
    html, text = ["<p><strong>Services</strong></p><ul>"], ["Services"]
    for row in vm["recurring"] + vm["one_offs"]:
        suffix = f": {row['fee_text']}" if vm["show_breakdown"] and row["fee_text"] else ""
        html.append(f"<li>{escape(row['service'])}{escape(suffix)}</li>")
        text.append(f"- {row['service']}{suffix}")
    html.append("</ul>")
    if vm["monthly_text"]:
        line = f"Monthly charge: {vm['monthly_text']} per month"
        html.append(f"<p><strong>{escape(line)}</strong></p>")
        text.append(line)
    if not vm["show_breakdown"] and vm["one_off_text"]:
        line = f"One-off charges: {vm['one_off_text']}"
        html.append(f"<p>{escape(line)}</p>")
        text.append(line)
    if vm["setup_text"]:
        line = f"One-off setup fee: {vm['setup_text']}"
        html.append(f"<p>{escape(line)}</p>")
        text.append(line)
    return "".join(html), "\n".join(text)


# ---------------------------------------------------------------- make and change


def uses_starter_wording() -> bool:
    return PipelineSettings.load().wording_is_starter


def services_changed_since(proposal: Proposal) -> bool:
    """True if the client's proposed services or fees differ from this proposal's lines."""

    def key(rows):
        return sorted((r["code"], r["fee"] or "", r["frequency"]) for r in rows)

    return key(build_lines(proposal.client)) != key(proposal.lines)


def withdraw_others(actor, client: Client, keep: Proposal | None = None) -> int:
    count = 0
    for old in client.proposals.filter(state__in=LIVE_STATES):
        if keep is not None and old.pk == keep.pk:
            continue
        old.state = State.WITHDRAWN
        old.save(update_fields=["state", "updated_at"])
        actionlinks.cancel_for(ActionLink.Purpose.PROPOSAL, old.pk)
        events.record(
            actor,
            "proposal.withdrawn",
            f"{who(actor)} withdrew proposal version {old.version} for {client.name} "
            "because a newer version was made.",
            client=client,
            target=old,
        )
        count += 1
    return count


@transaction.atomic
def create_proposal(actor, client: Client) -> Proposal:
    """A new version from the proposed services. Older live versions are withdrawn."""
    lines = build_lines(client)
    if not lines:
        raise ValidationError("Tick the services this client would take before making a proposal.")
    details = pipeline.ensure_details(client, actor)
    config = PipelineSettings.load()
    contact = client.main_contact
    latest = client.proposals.order_by("-version").first()
    version = latest.version + 1 if latest else 1
    withdraw_others(actor, client)
    proposal = Proposal.objects.create(
        client=client,
        version=version,
        lines=lines,
        monthly_total=monthly_total(lines),
        setup_fee=details.setup_fee,
        vat_rate=current_vat_rate(),
        valid_until=timezone.localdate() + timedelta(days=config.valid_days),
        opening_text=config.opening_text,
        what_next_html=config.what_next_html,
        contact=contact,
        prepared_by=actor,
    )
    events.record(
        actor,
        "proposal.created",
        f"{who(actor)} made proposal version {version} for {client.name}.",
        client=client,
        target=proposal,
    )
    return proposal


def set_switches(
    proposal: Proposal, *, show_breakdown: bool, show_inc_vat: bool, show_vat_text: bool
) -> Proposal:
    if not proposal.is_editable:
        raise ValidationError("Only a draft proposal can be changed.")
    proposal.show_breakdown = show_breakdown
    proposal.show_inc_vat = show_inc_vat
    proposal.show_vat_text = show_vat_text
    proposal.save(update_fields=["show_breakdown", "show_inc_vat", "show_vat_text", "updated_at"])
    return proposal


def proposal_url(token: str) -> str:
    return absolute(reverse("pipeline:proposal_page", args=[token]))


def default_message(proposal: Proposal, user) -> tuple[str, str]:
    """(subject, html) from the proposal template, with the link left for sending to fill in."""
    template = MessageTemplate.objects.get(key="proposal_send")
    ctx = comms.build_context(proposal.client, user=user, contact=proposal.contact)
    ctx.extra["proposal_summary_block"] = summary_block(proposal)
    ctx.extra["proposal_link"] = LINK_PLACEHOLDER
    subject, html, _, _ = comms.render_template(template, ctx)
    return subject, html


def blocking_problems(proposal: Proposal, *, body_html: str = "", to: str = "") -> list[str]:
    problems = []
    if not to.strip():
        problems.append("Choose who to send the proposal to.")
    if not proposal.lines:
        problems.append("The proposal has no services.")
    if proposal.valid_until < timezone.localdate():
        problems.append("The valid-until date has passed. Make a new version.")
    if body_html:
        if LINK_PLACEHOLDER not in body_html:
            problems.append("The message must keep the proposal link, or the client cannot reply.")
        for name in merge.unknown_fields(body_html):
            problems.append(f"Unknown merge field {{{{ {name} }}}}.")
        if "merge-unknown" in body_html:
            problems.append("The message still has an unfilled merge field.")
    return problems


def render_body(proposal: Proposal, *, acceptance: dict | None = None) -> str:
    """The proposal itself, as HTML for the page and the PDF."""
    return render_to_string(
        "pipeline/_proposal_body.html",
        {**view_model(proposal), "practice": PracticeSettings.load(), "acceptance": acceptance},
    )


def _store_pdf(actor, client: Client, name: str, data: bytes) -> Document:
    upload = SimpleUploadedFile(name, data, content_type="application/pdf")
    return client_services.store_document(
        actor, client, upload, category=Document.Category.ENGAGEMENT
    )


def _expiry(valid_until: date) -> datetime:
    """A link lasts to the end of the valid-until day (CORRECTIONS 20)."""
    return datetime.combine(
        valid_until + timedelta(days=1), time.min, tzinfo=timezone.get_current_timezone()
    )


@transaction.atomic
def send_proposal(
    actor,
    proposal: Proposal,
    *,
    to: str,
    cc: str = "",
    subject: str,
    body_html: str,
    attachments=(),
    uses_signature: bool = True,
) -> Proposal:
    """Freeze the proposal, make its PDF, and queue the email, approved by the sender."""
    proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.state != State.DRAFT:
        raise ValidationError("This proposal has already been sent.")
    body_html = clean_html(body_html)
    problems = blocking_problems(proposal, body_html=body_html, to=to)
    if not subject.strip():
        problems.append("Write a subject.")
    if proposal.contact is None:
        problems.append("The client has no main contact to send the proposal to.")
    if problems:
        raise ValidationError(" ".join(problems))
    client, practice = proposal.client, PracticeSettings.load()
    sent_on = timezone.localdate()
    data = pdf.render_pdf(
        f"<h1>Proposal for {escape(client.name)}</h1>{render_body(proposal)}",
        practice,
        on_date=sent_on,
    )
    document = _store_pdf(actor, client, f"Proposal v{proposal.version}.pdf", data)
    link, token = actionlinks.create(
        purpose=ActionLink.Purpose.PROPOSAL,
        contact=proposal.contact,
        client=client,
        object_id=proposal.pk,
        created_by=actor,
        expires_at=_expiry(proposal.valid_until),
    )
    body = body_html.replace(LINK_PLACEHOLDER, proposal_url(token))
    message = comms.create_message(
        client,
        created_by=actor,
        template=MessageTemplate.objects.filter(key="proposal_send").first(),
        to=to,
        cc=cc,
        subject=subject,
        body_html=body,
        contact=proposal.contact,
        reason=f"Proposal version {proposal.version}",
        attachments=attachments,
        uses_signature=uses_signature,
    )
    if comms.can_approve(actor, message):
        comms.approve(message, actor)
    proposal.document = document
    proposal.fingerprint = hashlib.sha256(data).hexdigest()
    proposal.message = message
    proposal.sent_to = to[:300]
    proposal.state = State.SENT
    proposal.sent_at = timezone.now()
    proposal.save()
    stage = PipelineStage.objects.filter(key="proposal_sent").first()
    details = ProspectDetails.objects.filter(client=client).select_related("stage").first()
    if (
        stage is not None
        and details is not None
        and details.stage.is_open
        and details.stage_id != stage.pk
        and not details.stage.is_on_hold
    ):
        pipeline.move_stage(actor, client, stage)
    pipeline.touch(client)
    events.record(
        actor,
        "proposal.sent",
        f"{who(actor)} sent proposal version {proposal.version} to {to} for {client.name}.",
        client=client,
        target=proposal,
        fingerprint=proposal.fingerprint,
    )
    return proposal


def cancel_link(actor, proposal: Proposal) -> int:
    count = actionlinks.cancel_for(ActionLink.Purpose.PROPOSAL, proposal.pk)
    if count:
        events.record(
            actor,
            "proposal.link_cancelled",
            f"{who(actor)} cancelled the link to proposal version {proposal.version} for "
            f"{proposal.client.name}.",
            client=proposal.client,
            target=proposal,
        )
    return count


def withdraw(actor, proposal: Proposal) -> Proposal:
    if proposal.state not in LIVE_STATES:
        raise ValidationError("Only a draft or an open proposal can be withdrawn.")
    proposal.state = State.WITHDRAWN
    proposal.save(update_fields=["state", "updated_at"])
    actionlinks.cancel_for(ActionLink.Purpose.PROPOSAL, proposal.pk)
    events.record(
        actor,
        "proposal.withdrawn",
        f"{who(actor)} withdrew proposal version {proposal.version} for {proposal.client.name}.",
        client=proposal.client,
        target=proposal,
    )
    return proposal


# ---------------------------------------------------------------- the client's side


def owner_of(client: Client):
    details = ProspectDetails.objects.filter(client=client).select_related("owner").first()
    return details.owner if details is not None else None


def notify_team(client: Client, message: str) -> None:
    from apps.onboarding.services import notify_staff

    notify_staff(
        client, message, reverse("onboarding:engagement", args=[client.pk]), owner_of(client)
    )


def note_viewed(proposal: Proposal, link: ActionLink) -> None:
    """The page was opened. Opening many times is fine; the first time is recorded."""
    now = timezone.now()
    if link.first_opened_at is None:
        link.first_opened_at = now
        link.save(update_fields=["first_opened_at", "updated_at"])
    if proposal.state == State.SENT:
        proposal.state = State.VIEWED
        proposal.viewed_at = now
        proposal.save(update_fields=["state", "viewed_at", "updated_at"])
        pipeline.touch(proposal.client, now)
        who_opened = proposal.contact.full_name if proposal.contact else "The client"
        events.record(
            None,
            "proposal.viewed",
            f"{who_opened} opened proposal version {proposal.version} for {proposal.client.name}.",
            client=proposal.client,
            target=proposal,
            actor_label=who_opened,
        )


def _decidable(link: ActionLink) -> Proposal:
    link = ActionLink.objects.select_for_update().get(pk=link.pk)
    if link.used_at is not None:
        raise ValidationError("A decision has already been made on this proposal.")
    if link.cancelled_at or link.expires_at <= timezone.now():
        raise ValidationError("This link is no longer valid.")
    proposal = Proposal.objects.select_for_update().get(pk=link.object_id, client=link.client)
    if proposal.state not in (State.SENT, State.VIEWED):
        raise ValidationError("This proposal can no longer be decided.")
    return proposal


def _acceptance_page(proposal, typed_name, email, when, ip, agent) -> dict:
    local = timezone.localtime(when)
    return {
        "name": typed_name,
        "email": email,
        "uk_time": f"{local:%d/%m/%Y %H:%M:%S %Z}",
        "ip": ip or "not recorded",
        "browser": agent or "not recorded",
        "fingerprint": proposal.fingerprint,
        "version": proposal.version,
    }


def on_proposal_accepted(client: Client, proposal: Proposal | None = None, actor=None) -> None:
    """Stage 7 hooks in here: the checklist is made and "Proposal accepted" is ticked.

    The stage becomes Won and the status `onboarding`. Proposed services stay proposed until the
    client is made live.
    """
    from apps.onboarding import services as onboarding

    details = pipeline.ensure_details(client, actor)
    if not details.stage.is_won:
        pipeline.move_stage(actor, client, pipeline.stage_of_kind(won=True))
    onboarding.on_proposal_accepted(client, actor=actor)


def accept(
    link: ActionLink, *, typed_name: str, agreed: bool, ip: str | None, agent: str
) -> Proposal:
    typed_name = " ".join((typed_name or "").split())
    if not agreed:
        raise ValidationError("Tick the box to say you accept this proposal.")
    if len(typed_name) < 3:
        raise ValidationError("Type your full name.")
    with transaction.atomic():
        proposal = _decidable(link)
        link = ActionLink.objects.get(pk=link.pk)
        now = timezone.now()
        client, practice = proposal.client, PracticeSettings.load()
        acceptance = _acceptance_page(proposal, typed_name, link.contact.email, now, ip, agent)
        data = pdf.render_pdf(
            f"<h1>Proposal for {escape(client.name)}</h1>"
            + render_body(proposal, acceptance=acceptance),
            practice,
            on_date=timezone.localtime(proposal.sent_at).date() if proposal.sent_at else None,
        )
        proposal.accepted_document = _store_pdf(
            None, client, f"Proposal v{proposal.version} (accepted).pdf", data
        )
        proposal.state = State.ACCEPTED
        proposal.decided_at = now
        proposal.decided_by = typed_name[:200]
        proposal.ip_address = ip
        proposal.user_agent = (agent or "")[:300]
        proposal.save()
        link.used_at = now
        link.save(update_fields=["used_at", "updated_at"])
        events.record(
            None,
            "proposal.accepted",
            f"{typed_name} accepted proposal version {proposal.version} for {client.name}.",
            client=client,
            target=proposal,
            actor_label=typed_name,
            fingerprint=proposal.fingerprint,
        )
        on_proposal_accepted(client, proposal)
    notify_team(client, f"{typed_name} accepted the proposal for {client.name}.")
    return proposal


def decline(link: ActionLink, *, reason: str, ip: str | None, agent: str) -> Proposal:
    with transaction.atomic():
        proposal = _decidable(link)
        link = ActionLink.objects.get(pk=link.pk)
        now = timezone.now()
        proposal.state = State.DECLINED
        proposal.decided_at = now
        proposal.decided_by = link.contact.full_name[:200]
        proposal.decline_reason = (reason or "").strip()[:500]
        proposal.ip_address = ip
        proposal.user_agent = (agent or "")[:300]
        proposal.save()
        link.used_at = now
        link.save(update_fields=["used_at", "updated_at"])
        pipeline.touch(proposal.client, now)
        events.record(
            None,
            "proposal.declined",
            f"{proposal.decided_by} declined proposal version {proposal.version} for "
            f"{proposal.client.name}." + (f" Reason: {proposal.decline_reason}" if reason else ""),
            client=proposal.client,
            target=proposal,
            actor_label=proposal.decided_by,
        )
    notify_team(proposal.client, f"The proposal for {proposal.client.name} was declined.")
    return proposal


def ask_question(link: ActionLink, *, text: str) -> Note:
    """A question from the client: a note on the timeline, and the prospect's owner is told."""
    text = (text or "").strip()
    if len(text) < 3:
        raise ValidationError("Write your question.")
    proposal = Proposal.objects.get(pk=link.object_id, client=link.client)
    if proposal.state not in (State.SENT, State.VIEWED):
        raise ValidationError("This proposal can no longer be asked about.")
    client = proposal.client
    asker = link.contact.full_name
    note = Note.objects.create(
        client=client,
        kind=Note.Kind.NOTE,
        text=f"Question from {asker} about proposal version {proposal.version}:\n{text[:2000]}",
        author=None,
    )
    pipeline.touch(client)
    events.record(
        None,
        "proposal.question",
        f"{asker} asked a question about proposal version {proposal.version} for {client.name}.",
        client=client,
        target=proposal,
        actor_label=asker,
        note_id=note.pk,
    )
    # The question also lands in the Requests inbox, where it can become a task.
    from apps.portal import requests as request_services
    from apps.portal.models import Request

    request_services.create_request(
        channel=Request.Channel.FORM,
        client=client,
        contact=link.contact,
        sender_name=asker,
        sender_email=link.contact.email,
        subject=f"Question about proposal version {proposal.version}",
        body=text[:2000],
        proposal_id=proposal.pk,
        actor_label=asker,
        notify=False,
    )
    notify_team(client, f"{asker} asked a question about the proposal for {client.name}.")
    return note


def expire_overdue(today: date | None = None) -> int:
    """Open proposals past their valid-until date become expired, and the owner is told."""
    today = today or timezone.localdate()
    count = 0
    for proposal in Proposal.objects.filter(
        state__in=(State.SENT, State.VIEWED), valid_until__lt=today
    ):
        proposal.state = State.EXPIRED
        proposal.save(update_fields=["state", "updated_at"])
        actionlinks.cancel_for(ActionLink.Purpose.PROPOSAL, proposal.pk)
        events.record(
            None,
            "proposal.expired",
            f"Proposal version {proposal.version} for {proposal.client.name} expired.",
            client=proposal.client,
            target=proposal,
        )
        notify_team(proposal.client, f"The proposal for {proposal.client.name} has expired.")
        count += 1
    return count


def recipients(client: Client) -> list[Contact]:
    """People with an email address who can receive the proposal."""
    links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
    return [link.contact for link in links if link.contact.email]
