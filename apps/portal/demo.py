"""Made-up portal data for development. Everything here is invented. Safe to run twice.

Three portal users on three different clients, open things to do of every kind, one finished
confirmation statement check, and fifteen requests across channels and states.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client, ClientContact, Document

from . import pforms, services
from . import requests as request_services
from .models import PortalItem, Request

PORTAL_CLIENTS = [
    "Copperleaf Consulting Ltd",
    "Harbour Bakes Ltd",
    "Wren and Finch Ltd",
]

# subject, body, channel, state, sender, urgency, client name or None
REQUESTS = [
    (
        "Copy of last year's accounts",
        "Could you email last year's signed accounts?",
        "form",
        "new",
        "Cass Copperleaf",
        "normal",
        "Copperleaf Consulting Ltd",
    ),
    (
        "New starter next month",
        "We have a new starter on 1 November. What do you need?",
        "portal",
        "new",
        "Harry Harbour",
        "urgent",
        "Harbour Bakes Ltd",
    ),
    (
        "VAT letter from HMRC",
        "We got a letter about our VAT. Photo attached on WhatsApp.",
        "whatsapp",
        "new",
        "Wynne Finch",
        "urgent",
        "Wren and Finch Ltd",
    ),
    (
        "Change of bank",
        "We have changed bank. New details to follow.",
        "email",
        "new",
        "Cass Copperleaf",
        "normal",
        "Copperleaf Consulting Ltd",
    ),
    (
        "Opening hours at Christmas",
        "Are you open between Christmas and New Year?",
        "phone",
        "new",
        "A caller",
        "normal",
        None,
    ),
    (
        "Can we meet about a loan?",
        "Thinking of borrowing for a new oven. Can we talk it through?",
        "in_person",
        "new",
        "Harry Harbour",
        "normal",
        "Harbour Bakes Ltd",
    ),
    (
        "Update our registered office",
        "We moved last week.",
        "portal",
        "in_progress",
        "Cass Copperleaf",
        "normal",
        "Copperleaf Consulting Ltd",
    ),
    (
        "Payroll for a leaver",
        "One member of staff left on Friday.",
        "form",
        "in_progress",
        "Harry Harbour",
        "normal",
        "Harbour Bakes Ltd",
    ),
    (
        "Dividend paperwork",
        "Please prepare the dividend vouchers for the quarter.",
        "email",
        "in_progress",
        "Cass Copperleaf",
        "normal",
        "Copperleaf Consulting Ltd",
    ),
    (
        "Mileage claim question",
        "What can we claim per mile?",
        "whatsapp",
        "in_progress",
        "Wynne Finch",
        "normal",
        "Wren and Finch Ltd",
    ),
    (
        "Thanks for the VAT return",
        "Just checking it was filed.",
        "form",
        "answered",
        "Wynne Finch",
        "normal",
        "Wren and Finch Ltd",
    ),
    (
        "Invoice copy",
        "Can you resend the March invoice?",
        "email",
        "answered",
        "Harry Harbour",
        "normal",
        "Harbour Bakes Ltd",
    ),
    (
        "Wrong client",
        "Sorry, sent to the wrong accountant.",
        "form",
        "closed",
        "Pat Elsewhere",
        "normal",
        None,
    ),
    (
        "Year-end meeting booked",
        "Booked by phone for 12 November.",
        "phone",
        "closed",
        "Cass Copperleaf",
        "normal",
        "Copperleaf Consulting Ltd",
    ),
    ("Cheap watches", "Buy now at a great price", "form", "spam", "Bot", "normal", None),
]


def _client(name: str) -> Client | None:
    return Client.objects.filter(name=name).first()


def _portal_user(client: Client) -> User | None:
    link = (
        client.client_contacts.filter(contact__email__gt="", resigned_on__isnull=True)
        .select_related("contact")
        .order_by("-is_main", "id")
        .first()
    )
    if link is None:
        return None
    contact = link.contact
    if contact.portal_user_id is None:
        user = User.objects.filter(email__iexact=contact.email).first()
        if user is not None and not user.is_portal:
            return None
        user = user or User.objects.create_user(
            contact.email, name=contact.full_name, kind=User.Kind.PORTAL, role=None
        )
        contact.portal_user = user
        contact.save(update_fields=["portal_user", "updated_at"])
    ClientContact.objects.filter(pk=link.pk).update(portal_access=True)
    return contact.portal_user


def _task(actor, client, title, steps):
    from apps.tasks import services as task_services
    from apps.tasks.models import Task, TaskKind

    task = Task.objects.filter(client=client, title=title).first()
    if task is None:
        task = task_services.create_task(
            actor, title=title, client=client, kind=TaskKind.COMPLIANCE, owner=client.manager,
            notify=False,
        )  # fmt: skip
        for position, (name, stops) in enumerate(steps, start=1):
            task.steps.create(name=name, position=position, stops_reminders=stops)
    return task


def seed() -> dict:
    from apps.accounts.models import Role
    from apps.onboarding import letters
    from apps.tasks import services as task_services

    actor = User.objects.filter(role__slug=Role.MANAGER, is_active=True).order_by("pk").first()
    clients = {name: _client(name) for name in PORTAL_CLIENTS}
    clients = {name: c for name, c in clients.items() if c is not None}
    users = {name: _portal_user(c) for name, c in clients.items()}
    made_items = 0
    copperleaf = clients.get("Copperleaf Consulting Ltd")
    harbour = clients.get("Harbour Bakes Ltd")
    wren = clients.get("Wren and Finch Ltd")

    if copperleaf and users.get(copperleaf.name):
        before = PortalItem.objects.count()
        records = _task(
            actor, copperleaf, "Year-end records for Copperleaf", [("Records received", True)]
        )
        services.create_item(
            actor, copperleaf, PortalItem.Kind.UPLOAD_RECORDS,
            "Upload your year-end records", task=records,
            due_date=timezone.localdate() + timedelta(days=14),
        )  # fmt: skip
        draft = Document.objects.filter(client=copperleaf, title="Draft accounts (demo)").first()
        if draft is None:
            from django.core.files.uploadedfile import SimpleUploadedFile

            from apps.clients import services as client_services

            draft = client_services.store_document(
                actor,
                copperleaf,
                SimpleUploadedFile(
                    "Draft accounts (demo).pdf", b"%PDF-1.4\n% made up\n", "application/pdf"
                ),
                category=Document.Category.ACCOUNTS,
            )
            draft.title = "Draft accounts (demo)"
            draft.save(update_fields=["title", "updated_at"])
        approval = _task(actor, copperleaf, "Approve draft accounts", [("Client approved", False)])
        services.create_item(
            actor, copperleaf, PortalItem.Kind.APPROVE_DOCUMENT,
            "Please read and approve your draft accounts", object_id=draft.pk, task=approval,
        )  # fmt: skip
        draft.shared_with_portal = True
        draft.save(update_fields=["shared_with_portal", "updated_at"])
        # A finished confirmation statement check, with one change.
        if not copperleaf.portal_forms.exists():
            confirm_task = _task(
                actor, copperleaf, "Confirmation statement check",
                [("Details sent to client", False), ("Client confirmed", True)],
            )  # fmt: skip
            item = services.create_item(
                actor, copperleaf, PortalItem.Kind.CONFIRM_DETAILS,
                "Check your company details", task=confirm_task, reuse=False,
            )  # fmt: skip
            form = pforms.form_for(item)
            post = QueryDict(mutable=True)
            for key in (
                "registered_office",
                "business_activity",
                "shareholders",
                "registered_email",
                "psc",
            ):
                post[f"{key}__choice"] = "no_change"
            post["officers__choice"] = "change"
            post["officers__text"] = "A new director joined on 1 September (demo)."
            pforms.submit(form, pforms.read_answers(form, post), users[copperleaf.name])
        made_items += PortalItem.objects.count() - before

    if harbour and users.get(harbour.name):
        before = PortalItem.objects.count()
        if not harbour.engagement_letters.exists():
            try:
                letter = letters.prepare_letter(actor, harbour)
                letters.send_letter(actor, letter)
            except ValidationError:
                pass
        services.create_item(
            actor, harbour, PortalItem.Kind.CLIENT_DETAILS, "Tell us about your business"
        )
        services.create_item(
            actor, harbour, PortalItem.Kind.CONFIRM_DETAILS, "Check your company details"
        )
        made_items += PortalItem.objects.count() - before

    if wren and users.get(wren.name):
        for proposal in wren.proposals.filter(state__in=("sent", "viewed")):
            proposal.save()  # the portal follows a proposal whenever it is saved

    for client in clients.values():
        request_services.ensure_token(client)

    new_requests = 0
    if Request.objects.count() < len(REQUESTS):
        for subject, body, channel, state, sender, urgency, client_name in REQUESTS:
            client = _client(client_name) if client_name else None
            if client_name and client is None:
                continue
            req = request_services.create_request(
                channel=channel,
                client=client,
                sender_name=sender,
                sender_email=f"{sender.split()[0].lower()}@example.com",
                subject=subject,
                body=body,
                urgency=urgency,
                logged_by=actor if channel in ("phone", "in_person", "whatsapp", "email") else None,
                notify=False,
            )
            new_requests += 1
            if state == "in_progress" and client is not None:
                from apps.portal.forms_staff import category_choices

                request_services.convert_to_task(
                    actor, req,
                    category=category_choices().first(), owner=client.manager or actor,
                )  # fmt: skip
            elif state == "answered":
                request_services.mark_answered(actor, req)
            elif state == "closed":
                request_services.close(actor, req, "Dealt with by phone (demo).")
            elif state == "spam":
                request_services.mark_spam(actor, req)
    del task_services
    return {
        "portal_users": sum(1 for u in users.values() if u),
        "portal_items": PortalItem.objects.count(),
        "requests": Request.objects.count(),
        "new_requests": new_requests,
        "new_items": made_items,
    }
