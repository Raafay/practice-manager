"""Saving, submitting and reviewing the two portal forms (spec 08 sections 4 and 5)."""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Contact, Document
from apps.comms import letters as pdf
from apps.core.models import PracticeSettings

from . import formspecs, services
from .models import PortalForm, PortalItem


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def form_for(item: PortalItem) -> PortalForm:
    kind = (
        PortalForm.Kind.CONFIRMATION
        if item.kind == PortalItem.Kind.CONFIRM_DETAILS
        else PortalForm.Kind.DETAILS
    )
    form, _ = PortalForm.objects.get_or_create(
        item=item, defaults={"client": item.client, "kind": kind}
    )
    return form


def sections_for(form: PortalForm, viewer=None):
    """viewer: the client contact filling it in, so other people's details are not shown to them."""
    if form.kind == PortalForm.Kind.CONFIRMATION:
        return formspecs.confirmation_sections(form.client)
    return formspecs.details_sections(form.client, viewer)


# ---------------------------------------------------------------- reading answers


def read_answers(form: PortalForm, post, viewer=None) -> dict:
    """Pull the answers out of a POST. Secrets are sealed straight away.

    viewer: the contact posting. Another person's fields were not shown to them, so
    a blank there keeps what was saved before, as for secrets.
    """
    sections = sections_for(form, viewer)
    answers: dict = {}
    if form.kind == PortalForm.Kind.CONFIRMATION:
        for section in sections:
            choice = post.get(f"{section.key}__choice", "")
            text = (post.get(f"{section.key}__text", "") or "").strip()[:2000]
            if choice in ("no_change", "change"):
                answers[section.key] = {
                    "choice": choice,
                    "text": text,
                    "held": section.held,
                }
        return answers
    previous = form.answers or {}
    for field in formspecs.all_fields(sections):
        value = (post.get(field.key, "") or "").strip()[:2000]
        if field.secret or field.private:
            # Blank means "keep what is held". A secret is stored sealed.
            if value:
                answers[field.key] = formspecs.seal(value) if field.secret else value
            elif field.key in previous:
                answers[field.key] = previous[field.key]
        elif value:
            answers[field.key] = value
    return answers


def visible_answers(form: PortalForm, answers: dict, viewer) -> dict:
    """Answers this viewer may see: never another person's saved details."""
    private = {f.key for f in formspecs.all_fields(sections_for(form, viewer)) if f.private}
    return {key: value for key, value in (answers or {}).items() if key not in private}


def check_complete(form: PortalForm, answers: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if form.kind == PortalForm.Kind.CONFIRMATION:
        for section in sections_for(form):
            entry = answers.get(section.key)
            if not entry:
                errors[section.key] = "Choose “No change” or “There is a change”."
            elif entry["choice"] == "change" and len(entry["text"]) < 3:
                errors[section.key] = "Describe the change."
        return errors
    for field in formspecs.all_fields(sections_for(form)):
        value = answers.get(field.key)
        if value and field.input == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors[field.key] = "Enter a valid date."
    return errors


# ---------------------------------------------------------------- save and submit


def save_draft(form: PortalForm, answers: dict) -> PortalForm:
    if form.state != PortalForm.State.DRAFT:
        raise ValidationError("This form has already been sent.")
    form.answers = answers
    form.save(update_fields=["answers", "updated_at"])
    return form


@transaction.atomic
def submit(form: PortalForm, answers: dict, user) -> PortalForm:
    form = PortalForm.objects.select_for_update().get(pk=form.pk)
    if form.state != PortalForm.State.DRAFT:
        raise ValidationError("This form has already been sent.")
    errors = check_complete(form, answers)
    if errors:
        raise ValidationError(list(errors.values()))
    contact = getattr(user, "portal_contact", None)
    form.answers = answers
    form.state = PortalForm.State.SUBMITTED
    form.submitted_at = timezone.now()
    form.submitted_by = contact
    form.save()
    events.record(
        user,
        "portal.form_submitted",
        f"{contact.full_name if contact else user} sent the "
        f"{form.get_kind_display().lower()} for {form.client.name}.",
        client=form.client,
        target=form,
    )
    if form.kind == PortalForm.Kind.CONFIRMATION:
        _finish_confirmation(form, user, contact)
    else:
        link = reverse("portal:review", args=[form.pk])
        services.notify_owner(
            form.client, f"{form.client.name} sent their details form. Review it.", link
        )
    services.complete_item(form.item, contact, actor=user)
    return form


def _finish_confirmation(form: PortalForm, user, contact) -> None:
    from apps.tasks import services as task_services

    client = form.client
    changes = [
        s.title for s in sections_for(form) if form.answers.get(s.key, {}).get("choice") == "change"
    ]
    document = _confirmation_pdf(form, contact)
    form.document = document
    form.save(update_fields=["document", "updated_at"])
    task = form.item.task
    if task is not None and not task.is_cancelled:
        step = (
            task.steps.filter(name__iexact="Client confirmed", done_at__isnull=True).first()
            or task.steps.filter(stops_reminders=True, done_at__isnull=True).first()
        )
        if step is not None:
            task_services.toggle_step(user, step, True)
    owner = (task.owner if task is not None else None) or services.client_services_owner(client)
    message = f"{client.name} confirmed their company details" + (
        f", with changes to: {', '.join(changes)}." if changes else " with no changes."
    )
    if owner is not None:
        link = (
            task_services.task_url(task)
            if task is not None
            else reverse("clients:documents", args=[client.pk])
        )
        events.notify(owner, message, link)


def _confirmation_pdf(form: PortalForm, contact) -> Document:
    client, practice = form.client, PracticeSettings.load()
    rows = []
    for section in sections_for(form):
        entry = form.answers.get(section.key, {})
        changed = entry.get("choice") == "change"
        answer = "There is a change: " + entry.get("text", "") if changed else "No change"
        rows.append(
            "<tr><td style='vertical-align:top;padding:6px 8px;border-bottom:1px solid #ccc'>"
            f"<strong>{escape(section.title)}</strong><br>"
            "<span style='white-space:pre-line'>"
            f"{escape(section.held or 'Nothing held')}</span></td>"
            f"<td style='vertical-align:top;padding:6px 8px;border-bottom:1px solid #ccc"
            f"{';background:#fff3cd' if changed else ''}'>"
            f"{'<strong>CHANGE</strong><br>' if changed else ''}{escape(answer)}</td></tr>"
        )
    who_said = contact.full_name if contact else "the client"
    html = (
        f"<h1>Confirmation statement check: {escape(client.name)}</h1>"
        f"<p>Completed by {escape(who_said)} on "
        f"{timezone.localtime(form.submitted_at):%d/%m/%Y at %H:%M}.</p>"
        "<table style='width:100%;border-collapse:collapse'><tr><th style='text-align:left'>"
        "What Companies House holds</th><th style='text-align:left'>The client's answer</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    data = pdf.render_pdf(html, practice)
    upload = SimpleUploadedFile(
        f"Confirmation statement check {timezone.localdate():%Y-%m-%d}.pdf",
        data,
        content_type="application/pdf",
    )
    document = client_services.store_document(
        None, client, upload, category=Document.Category.CORRESPONDENCE
    )
    document.source = Document.Source.SYSTEM
    document.shared_with_portal = True
    document.save(update_fields=["source", "shared_with_portal", "updated_at"])
    return document


# ---------------------------------------------------------------- staff review (section 5)


def review_rows(form: PortalForm) -> list[dict]:
    """Each answer beside the current record. Only answers that differ need a decision."""
    rows = []
    for section in sections_for(form):
        for field in section.fields:
            answer = form.answers.get(field.key)
            if not answer:
                continue
            new_value = formspecs.unseal(answer)
            old_value = ""
            same = False
            if field.target and field.target[0] == "client":
                current = getattr(form.client, field.target[1], "") or ""
                old_value = str(current)
            elif field.target and field.target[0] == "contact":
                contact = Contact.objects.filter(pk=field.target[1]).first()
                current = getattr(contact, field.target[2], "") if contact else ""
                old_value = current.isoformat() if isinstance(current, date) else str(current or "")
            same = bool(field.target) and old_value.strip() == new_value.strip()
            decision = form.review.get(field.key, "")
            rows.append(
                {
                    "section": section.title,
                    "key": field.key,
                    "label": field.label,
                    "secret": field.secret,
                    "current": field.current,
                    "answer": formspecs.shown(field, answer),
                    "same": same,
                    "has_target": field.target is not None,
                    "decision": decision or ("same" if same else ""),
                }
            )
    return rows


def _field(form: PortalForm, key: str):
    for field in formspecs.all_fields(sections_for(form)):
        if field.key == key:
            return field
    raise ValidationError("That field is not on this form.")


@transaction.atomic
def apply_field(actor, form: PortalForm, key: str) -> None:
    form = PortalForm.objects.select_for_update().get(pk=form.pk)
    if form.state != PortalForm.State.SUBMITTED:
        raise ValidationError("This form has already been reviewed.")
    field = _field(form, key)
    answer = form.answers.get(key)
    if not answer:
        raise ValidationError("There is no answer to apply.")
    if form.review.get(key):
        return
    value = formspecs.unseal(answer)
    client = form.client
    if field.target is None:
        client_services.add_note(
            actor,
            client,
            f"From the client details form: {field.label}: {value}",
        )
    else:
        if field.target[0] == "client":
            instance, attr = client, field.target[1]
        else:
            instance, attr = Contact.objects.get(pk=field.target[1]), field.target[2]
        model_field = instance._meta.get_field(attr)
        if model_field.get_internal_type() == "DateField":
            value = date.fromisoformat(value)
        setattr(instance, attr, value)
        instance.save(update_fields=[attr, "updated_at"])
        events.record(
            actor,
            "portal.field_applied",
            f"{who(actor)} applied “{field.label}” from the client details form"
            + (" (value not shown)." if field.secret else f": {str(value)[:80]}."),
            client=client,
            target=instance,
            field=attr,
        )
    form.review = {**form.review, key: "applied"}
    form.save(update_fields=["review", "updated_at"])
    _finish_if_done(actor, form)


@transaction.atomic
def dismiss_field(actor, form: PortalForm, key: str) -> None:
    form = PortalForm.objects.select_for_update().get(pk=form.pk)
    if form.state != PortalForm.State.SUBMITTED:
        raise ValidationError("This form has already been reviewed.")
    _field(form, key)
    if not form.review.get(key):
        form.review = {**form.review, key: "dismissed"}
        form.save(update_fields=["review", "updated_at"])
    _finish_if_done(actor, form)


def apply_all(actor, form: PortalForm) -> int:
    count = 0
    for row in review_rows(form):
        if not row["decision"]:
            apply_field(actor, PortalForm.objects.get(pk=form.pk), row["key"])
            count += 1
    return count


def dismiss_rest(actor, form: PortalForm) -> int:
    count = 0
    for row in review_rows(form):
        if not row["decision"]:
            dismiss_field(actor, PortalForm.objects.get(pk=form.pk), row["key"])
            count += 1
    return count


def _finish_if_done(actor, form: PortalForm) -> None:
    from apps.onboarding import services as onboarding

    form.refresh_from_db()
    if form.state != PortalForm.State.SUBMITTED:
        return
    if any(not row["decision"] for row in review_rows(form)):
        return
    form.state = PortalForm.State.REVIEWED
    form.reviewed_at = timezone.now()
    form.reviewed_by = actor
    form.save(update_fields=["state", "reviewed_at", "reviewed_by", "updated_at"])
    events.record(
        actor,
        "portal.form_reviewed",
        f"{who(actor)} finished reviewing the client details form for {form.client.name}.",
        client=form.client,
        target=form,
    )
    onboarding.tick(
        form.client,
        "client_details",
        actor=actor,
        note="Client details form reviewed.",
    )
