"""Chasing overdue fees: one drafted message per client, always waiting for approval."""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps import events
from apps.comms import services as comms
from apps.comms.models import MessageTemplate, QueuedMessage

from . import invoicing

# (minimum days overdue, template key), oldest tier first.
TIERS = [(30, "fees_chase_30"), (14, "fees_chase_14"), (7, "fees_chase_7")]

HELLO = "<p>Dear {{ contact.first_name }},</p>"
BYE = "<p>Kind regards,<br>{{ user.name }}</p>"

TEMPLATES = [
    {
        "key": "fees_chase_7",
        "name": "Fees: gentle reminder (7 days)",
        "subject": "A reminder about our invoice for {{ client.name }}",
        "body": HELLO + "<p>Our records show the invoices below are a little past their due "
        "date. They may simply have crossed with your payment, in which case thank you and "
        "please ignore this note.</p>{{ outstanding_invoices }}"
        "<p>If anything looks wrong, just reply and we will sort it out.</p>" + BYE,
    },
    {
        "key": "fees_chase_14",
        "name": "Fees: second reminder (14 days)",
        "subject": "Overdue invoices for {{ client.name }}",
        "body": HELLO + "<p>We have not yet received payment for the invoices below, which are "
        "now two weeks or more overdue. Please arrange payment this week, or tell us if there "
        "is a problem we can help with.</p>{{ outstanding_invoices }}" + BYE,
    },
    {
        "key": "fees_chase_30",
        "name": "Fees: final reminder (30 days or more)",
        "subject": "Final reminder: overdue invoices for {{ client.name }}",
        "body": HELLO + "<p>The invoices below have been overdue for a month or more. Please "
        "pay them in the next seven days, or call us to agree a plan. Without payment or a "
        "plan we may have to pause our services.</p>{{ outstanding_invoices }}" + BYE,
    },
]


def tier_for(days_overdue: int) -> str | None:
    for minimum, key in TIERS:
        if days_overdue >= minimum:
            return key
    return None


def draft_chase_emails(actor, today: date | None = None) -> dict:
    """Queue one message per client with overdue invoices. Nothing is sent from here.

    The template is chosen by the age of the client's oldest overdue invoice. A message is never
    made twice for the same client, tier and oldest invoice. Every message waits for approval
    whatever its template's send mode, and approving needs `comms.approve_fees`.
    """
    today = today or timezone.localdate()
    made, skipped = 0, []
    for group in invoicing.overdue_groups(today):
        client = group.client
        if client is None:
            skipped.append((group.name, "Not matched to a client"))
            continue
        key = tier_for(group.oldest_days)
        if key is None:
            continue
        template = MessageTemplate.objects.filter(key=key, active=True).first()
        if template is None:
            skipped.append((client.name, "The template is switched off"))
            continue
        reason = comms.skip_reason(client, automatic=False)
        if reason:
            skipped.append((client.name, reason))
            continue
        oldest = min(group.invoices, key=lambda i: i.due_date)
        duplicate_key = f"chase-{client.pk}-{key}-{oldest.xero_id}"
        if QueuedMessage.objects.filter(duplicate_key=duplicate_key).exists():
            skipped.append((client.name, "Already drafted"))
            continue
        recipients = comms.reminder_recipients(client, main_only=True)
        if not recipients:
            skipped.append((client.name, "No contact with an email address"))
            continue
        ctx = comms.build_context(client, user=actor, contact=recipients[0])
        ctx.extra["today"] = today
        subject, html, text, _problems = comms.render_template(template, ctx)
        message = comms.create_message(
            client,
            created_by=actor,
            template=template,
            to=", ".join(c.email for c in recipients),
            subject=subject,
            body_html=html,
            body_text=text,
            reason=f"Overdue fees: {len(group.invoices)} invoice(s), oldest {group.oldest_days}d",
            contact=recipients[0],
            duplicate_key=duplicate_key,
        )
        made += 1 if message else 0
    events.record(
        actor,
        "finance.chase_drafted",
        f"{actor.name} drafted {made} fee chase message(s).",
        made=made,
        skipped=len(skipped),
    )
    return {"made": made, "skipped": skipped}
