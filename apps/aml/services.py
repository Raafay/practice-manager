"""Identity checks, risk assessments and the AML state of a client (spec 06 sections 3 to 5)."""

from __future__ import annotations

from datetime import date, timedelta

import django.dispatch
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, ClientContact, Contact, Document
from apps.core.dates import add_months
from apps.core.html import clean_html

from .models import (
    LEVEL_RANK,
    AmlSettings,
    IdentityCheck,
    ReviewPrompt,
    RiskAssessment,
    RiskQuestion,
)

# Sent when an assessment is approved (assessment). Onboarding listens to tick its line.
assessment_approved = django.dispatch.Signal()
# Sent when the set of identity checks or their states change (client).
identity_changed = django.dispatch.Signal()

ID_ROLES = {"director", "partner", "member", "trustee"}
Check = IdentityCheck.State
A = RiskAssessment.State


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


# ---------------------------------------------------------------- identity


def proposed_people(client: Client) -> list[tuple[Contact, list[str]]]:
    """Who needs identifying, from contact roles, with the reason for each."""
    out = []
    links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
    for link in links:
        reasons = []
        if link.is_main:
            reasons.append("Main contact")
        for role in link.roles or []:
            if role in ID_ROLES:
                reasons.append(dict(ClientContact.Role.choices).get(role, role))
        if "psc" in (link.roles or []) or (
            link.shareholding_percent is not None and link.shareholding_percent > 25
        ):
            reasons.append("Owner with more than 25%")
        if reasons:
            out.append((link.contact, list(dict.fromkeys(reasons))))
    return out


def sync_checks(client: Client) -> int:
    """Make a check row for each proposed person who lacks one. Safe to run twice."""
    made = 0
    for contact, _ in proposed_people(client):
        _, created = IdentityCheck.objects.get_or_create(client=client, contact=contact)
        made += int(created)
    return made


def listed_checks(client: Client):
    return client.identity_checks.filter(excluded=False).select_related("contact")


def all_verified(client: Client) -> bool:
    checks = list(listed_checks(client))
    return bool(checks) and all(c.state == Check.VERIFIED for c in checks)


def identity_progress(client: Client) -> tuple[int, int]:
    checks = list(listed_checks(client))
    return len([c for c in checks if c.state == Check.VERIFIED]), len(checks)


def _changed(client: Client) -> None:
    identity_changed.send(sender=Client, client=client)


def add_person(actor, client: Client, contact: Contact, reason: str) -> IdentityCheck:
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say why this person is being added.")
    check, _ = IdentityCheck.objects.get_or_create(client=client, contact=contact)
    check.excluded = False
    check.excluded_reason = ""
    check.added_by_hand = True
    check.added_reason = reason[:300]
    check.save()
    events.record(
        actor,
        "aml.person_added",
        f"{who(actor)} added {contact.full_name} to the people to identify for {client.name}: "
        f"{reason}",
        client=client,
        target=check,
    )
    _changed(client)
    return check


def remove_person(actor, check: IdentityCheck, reason: str) -> IdentityCheck:
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say why this person does not need identifying.")
    check.excluded = True
    check.excluded_reason = reason[:300]
    check.save()
    events.record(
        actor,
        "aml.person_removed",
        f"{who(actor)} took {check.contact.full_name} off the people to identify for "
        f"{check.client.name}: {reason}",
        client=check.client,
        target=check,
    )
    _changed(check.client)
    return check


def update_check(actor, check: IdentityCheck, data: dict) -> IdentityCheck:
    """Save the form fields. Verified needs a method, a document type and an uploaded copy."""
    state = data.get("state") or check.state
    if state == Check.VERIFIED:
        if not data.get("method"):
            raise ValidationError("Say how the identity was verified.")
        if not data.get("document_type"):
            raise ValidationError("Say which document was seen.")
        if not check.documents.filter(deleted_at__isnull=True).exists():
            raise ValidationError(
                "Upload a copy of the document first. The upload is the record: "
                "document numbers are not stored."
            )
    old = check.state
    for field in ("method", "document_type", "document_expiry", "proof_of_address", "notes"):
        if field in data:
            setattr(check, field, data[field])
    check.state = state
    if state == Check.VERIFIED and old != Check.VERIFIED:
        check.verified_by = actor
        check.verified_at = timezone.now()
    elif state != Check.VERIFIED:
        check.verified_by = None
        check.verified_at = None
    check.expiry_notified_on = None if "document_expiry" in data else check.expiry_notified_on
    check.save()
    events.record(
        actor,
        "aml.identity_updated",
        f"{who(actor)} set the identity check for {check.contact.full_name} at "
        f"{check.client.name} to {state.replace('_', ' ')}.",
        client=check.client,
        target=check,
        old=old,
        new=state,
    )
    _changed(check.client)
    return check


def upload_for_check(actor, check: IdentityCheck, upload, *, proof_of_address=False) -> Document:
    """Store an identity or proof-of-address file as a sensitive document and link it."""
    category = (
        Document.Category.PROOF_OF_ADDRESS if proof_of_address else Document.Category.IDENTITY
    )
    document = client_services.store_document(
        actor, check.client, upload, category=category, contact=check.contact, sensitive=True
    )
    check.documents.add(document)
    if check.state in (Check.NOT_STARTED, Check.REQUESTED):
        check.state = Check.RECEIVED
        check.save(update_fields=["state", "updated_at"])
        _changed(check.client)
    return document


# ---------------------------------------------------------------- risk: scoring


def active_questions():
    return RiskQuestion.objects.filter(active=True)


def score_answers(answers: dict) -> tuple[int, bool]:
    """Total score, and whether any answer means enhanced checks."""
    score = sum(int(a.get("score", 0)) for a in answers.values())
    enhanced = any(a.get("enhanced") for a in answers.values())
    return score, enhanced


def suggest(answers: dict) -> tuple[int, bool, str]:
    score, enhanced = score_answers(answers)
    return score, enhanced, AmlSettings.load().level_for(score, enhanced)


def _answer_entry(question: RiskQuestion, value: str, note="", checked_on="", checked_how=""):
    option = question.option(value)
    if option is None:
        raise ValidationError(f"Choose an answer for: {question.text}")
    return {
        "text": question.text,
        "section": question.section,
        "answer": value,
        "label": option["label"],
        "score": int(option["score"]),
        "enhanced": bool(option.get("enhanced")),
        "records_check": question.records_check,
        "note": (note or "")[:500],
        "checked_on": checked_on or "",
        "checked_how": (checked_how or "")[:300],
    }


def current_assessment(client: Client) -> RiskAssessment | None:
    """The latest approved assessment."""
    return client.risk_assessments.filter(state=A.APPROVED).first()


def open_assessment(client: Client) -> RiskAssessment | None:
    return client.risk_assessments.filter(state__in=RiskAssessment.OPEN_STATES).first()


@transaction.atomic
def start_assessment(actor, client: Client, reason: str = "") -> RiskAssessment:
    """A new version, starting from the previous answers when there are any."""
    existing = open_assessment(client)
    if existing is not None:
        return existing
    previous = client.risk_assessments.exclude(state=A.DRAFT).first()
    version = (
        client.risk_assessments.order_by("-version").values_list("version", flat=True).first() or 0
    ) + 1
    answers = {}
    if previous is not None:
        wanted = {str(q.pk) for q in active_questions()}
        answers = {k: dict(v) for k, v in previous.answers.items() if k in wanted}
    assessment = RiskAssessment.objects.create(
        client=client,
        version=version,
        answers=answers,
        assessed_by=actor,
        review_reason=reason[:300],
    )
    assessment.score, assessment.enhanced_needed, assessment.suggested_level = suggest(answers)
    assessment.save()
    events.record(
        actor,
        "aml.assessment_started",
        f"{who(actor)} started risk assessment version {version} for {client.name}"
        + (f" ({reason})." if reason else "."),
        client=client,
        target=assessment,
    )
    resolve_prompts(client)
    return assessment


def apply_form(assessment: RiskAssessment, data) -> list[str]:
    """Read answers from a form post into the draft. Returns the problems, if any."""
    problems = []
    answers = {}
    for question in active_questions():
        key = str(question.pk)
        value = data.get(f"q_{key}", "")
        if not value:
            continue
        try:
            answers[key] = _answer_entry(
                question,
                value,
                data.get(f"n_{key}", ""),
                data.get(f"d_{key}", ""),
                data.get(f"h_{key}", ""),
            )
        except ValidationError as error:
            problems.extend(error.messages)
    assessment.answers = answers
    assessment.score, assessment.enhanced_needed, assessment.suggested_level = suggest(answers)
    assessment.level = data.get("level", "") or assessment.level
    assessment.level_reason = (data.get("level_reason", "") or "")[:300]
    assessment.enhanced_notes = data.get("enhanced_notes", "") or ""
    assessment.summary = clean_html(data.get("summary", "") or "")
    return problems


def submit_problems(assessment: RiskAssessment) -> list[str]:
    problems = []
    for question in active_questions():
        entry = assessment.answers.get(str(question.pk))
        if entry is None:
            problems.append(f"Answer: {question.text}")
            continue
        if question.records_check and not (entry["checked_on"] and entry["checked_how"]):
            problems.append(f"Record the date checked and how for: {question.text}")
    level = assessment.level or assessment.suggested_level
    suggested = assessment.suggested_level
    lower = bool(level and suggested and LEVEL_RANK[level] < LEVEL_RANK[suggested])
    if lower and not assessment.level_reason.strip():
        problems.append("Give a reason for setting a lower level than suggested.")
    if assessment.enhanced_needed and not assessment.enhanced_notes.strip():
        problems.append(
            "Enhanced checks are needed: say what extra evidence was obtained, the source of "
            "funds and wealth, and that the owner approved."
        )
    return problems


@transaction.atomic
def save_draft(actor, assessment: RiskAssessment, data, *, submit: bool = False) -> list[str]:
    """Save the form. With submit, check everything and send it for approval."""
    if not assessment.is_editable:
        raise ValidationError("This assessment can no longer be edited.")
    problems = apply_form(assessment, data)
    if submit:
        if not assessment.level:
            assessment.level = assessment.suggested_level
        problems += submit_problems(assessment)
    if submit and not problems:
        assessment.state = A.SUBMITTED
        assessment.assessed_by = actor
        assessment.assessed_at = timezone.now()
        assessment.send_back_reason = ""
    assessment.save()
    if submit and not problems:
        events.record(
            actor,
            "aml.assessment_submitted",
            f"{who(actor)} submitted risk assessment version {assessment.version} for "
            f"{assessment.client.name}: score {assessment.score}, level {assessment.level}.",
            client=assessment.client,
            target=assessment,
            score=assessment.score,
            level=assessment.level,
        )
        for approver in approvers(exclude=actor if assessment.level == "high" else None):
            events.notify(
                approver,
                f"Risk assessment for {assessment.client.name} is waiting for approval.",
                f"/clients/{assessment.client_id}/risk/",
            )
    return problems


def approvers(exclude=None):
    from apps.accounts.models import User

    return [
        u
        for u in User.objects.staff().filter(is_active=True)
        if u.can("aml.approve") and (exclude is None or u.pk != exclude.pk)
    ]


def can_approve(user, assessment: RiskAssessment) -> tuple[bool, str]:
    if not user.can("aml.approve"):
        return False, "You do not have the right to approve assessments."
    own_high = assessment.level == "high" and assessment.assessed_by_id == user.pk
    if own_high and approvers(exclude=user):
        return (
            False,
            "A high-risk assessment must be approved by someone other than its assessor.",
        )
    return True, ""


def _snapshot_html(client: Client) -> str:
    snap = getattr(client, "ch_snapshot", None)
    if snap is None:
        return ""
    profile = snap.profile or {}
    parts = [
        f"<h1>Companies House record: {escape(client.name)}</h1>",
        f"<p>Company number {escape(snap.company_number)}. Last synced "
        f"{timezone.localtime(snap.synced_at):%d/%m/%Y %H:%M}.</p>",
        f"<p>Status: {escape(str(profile.get('company_status', '')))}. "
        f"Incorporated: {escape(str(profile.get('date_of_creation', '')))}.</p>",
        "<h2>Officers</h2><ul>",
    ]
    for o in snap.officers or []:
        parts.append(
            f"<li>{escape(o.get('name', ''))}: {escape(str(o.get('officer_role', '')))}, "
            f"appointed {escape(str(o.get('appointed_on', '')))}"
            + (f", resigned {escape(str(o['resigned_on']))}" if o.get("resigned_on") else "")
            + "</li>"
        )
    parts.append("</ul><h2>Persons with significant control</h2><ul>")
    for o in snap.owners or []:
        nature = "; ".join(o.get("natures_of_control") or [])
        parts.append(
            f"<li>{escape(o.get('name', ''))}: {escape(nature)}"
            + (f" (ceased {escape(str(o['ceased_on']))})" if o.get("ceased_on") else "")
            + "</li>"
        )
    parts.append("</ul>")
    return "".join(parts)


def save_ch_snapshot(actor, client: Client) -> Document | None:
    html = _snapshot_html(client)
    if not html:
        return None
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.comms import letters as pdf
    from apps.core.models import PracticeSettings

    data = pdf.render_pdf(html, PracticeSettings.load())
    upload = SimpleUploadedFile(
        f"Companies House record {timezone.localdate():%Y-%m-%d}.pdf",
        data,
        content_type="application/pdf",
    )
    return client_services.store_document(actor, client, upload, category=Document.Category.OTHER)


@transaction.atomic
def approve(actor, assessment: RiskAssessment) -> RiskAssessment:
    assessment = RiskAssessment.objects.select_for_update().get(pk=assessment.pk)
    allowed, why = can_approve(actor, assessment)
    if not allowed:
        if not actor.can("aml.approve"):
            raise PermissionDenied
        raise ValidationError(why)
    if assessment.state != A.SUBMITTED:
        raise ValidationError("Only an assessment awaiting approval can be approved.")
    client = assessment.client
    today = timezone.localdate()
    assessment.client.risk_assessments.filter(state=A.APPROVED).update(state=A.SUPERSEDED)
    assessment.state = A.APPROVED
    assessment.approved_by = actor
    assessment.approved_at = timezone.now()
    assessment.next_review_due = add_months(
        today, AmlSettings.load().review_months(assessment.level)
    )
    assessment.ch_snapshot_document = save_ch_snapshot(actor, client)
    assessment.save()
    events.record(
        actor,
        "aml.assessment_approved",
        f"{who(actor)} approved risk assessment version {assessment.version} for {client.name} "
        f"at {assessment.level} risk. Next review {assessment.next_review_due:%d/%m/%Y}.",
        client=client,
        target=assessment,
        level=assessment.level,
        score=assessment.score,
    )
    assessment_approved.send(sender=RiskAssessment, assessment=assessment, actor=actor)
    return assessment


def send_back(actor, assessment: RiskAssessment, reason: str) -> RiskAssessment:
    if not actor.can("aml.approve"):
        raise PermissionDenied
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say what needs changing.")
    if assessment.state != A.SUBMITTED:
        raise ValidationError("Only an assessment awaiting approval can be sent back.")
    assessment.state = A.SENT_BACK
    assessment.send_back_reason = reason[:300]
    assessment.save()
    events.record(
        actor,
        "aml.assessment_sent_back",
        f"{who(actor)} sent risk assessment version {assessment.version} for "
        f"{assessment.client.name} back: {reason}",
        client=assessment.client,
        target=assessment,
    )
    if assessment.assessed_by and assessment.assessed_by.is_active:
        events.notify(
            assessment.assessed_by,
            f"The risk assessment for {assessment.client.name} was sent back: {reason}",
            f"/clients/{assessment.client_id}/risk/",
        )
    return assessment


# ---------------------------------------------------------------- state


def state_of(client: Client, today: date | None = None) -> tuple[str, str, str]:
    """(key, label, tone): the AML state worked out, never stored."""
    today = today or timezone.localdate()
    assessments = list(client.risk_assessments.all())
    open_one = next((a for a in assessments if a.state in RiskAssessment.OPEN_STATES), None)
    approved = next((a for a in assessments if a.state == A.APPROVED), None)
    if open_one is not None and open_one.state == A.SUBMITTED:
        return "awaiting_approval", "Awaiting approval", "accent"
    if approved is not None:
        due = approved.next_review_due
        if due is not None and due < today:
            return "review_overdue", "Review overdue", "red"
        if due is not None and due <= today + timedelta(days=30):
            return "review_due", "Review due", "amber"
        return "approved", "Approved", "green"
    if open_one is not None:
        return "in_progress", "In progress", "accent"
    if (
        client.status in (Client.Status.ACTIVE, Client.Status.PAUSED)
        and not client.onboarding_items.exists()
    ):
        return "needs_review", "Needs review (imported)", "amber"
    return "not_started", "Not started", "neutral"


def level_of(client: Client) -> str:
    approved = current_assessment(client)
    return approved.level if approved else ""


# ---------------------------------------------------------------- prompts


def prompt_review(client: Client, reason: str) -> ReviewPrompt | None:
    """Note that a review is due sooner than its date. One open prompt per reason."""
    if client.status in (Client.Status.FORMER, Client.Status.LOST, Client.Status.PROSPECT):
        return None
    if client.risk_assessments.count() == 0:
        return None  # nothing to review yet
    existing = client.aml_review_prompts.filter(reason=reason, resolved_at__isnull=True).first()
    if existing:
        return existing
    prompt = ReviewPrompt.objects.create(client=client, reason=reason[:300])
    events.record(
        None,
        "aml.review_prompted",
        f"An AML review is prompted for {client.name}: {reason}",
        client=client,
        target=prompt,
    )
    from apps.onboarding import services as onboarding

    onboarding.notify_staff(
        client,
        f"AML review prompted for {client.name}: {reason}",
        f"/clients/{client.pk}/risk/",
    )
    return prompt


def open_prompts(client: Client):
    return client.aml_review_prompts.filter(resolved_at__isnull=True)


def resolve_prompts(client: Client) -> None:
    client.aml_review_prompts.filter(resolved_at__isnull=True).update(resolved_at=timezone.now())
