"""Made-up queued messages for development. Everything here is invented.

Switches two reminder schedules on (in demo data only), runs the schedule job, and
adds hand-made messages so the Queued page shows every state. Safe to run twice.
Nothing is sent: sent and failed rows are written directly.
"""

from datetime import date, timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client

from . import schedules, services
from .models import QueuedMessage, ReminderSchedule

DEMO_SCHEDULES = ("vat_records", "ct_payment")


def seed(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    for key in DEMO_SCHEDULES:
        ReminderSchedule.objects.filter(key=key).update(active=True)
    made = 0
    for back in range(0, 4):
        made += schedules.run_all(today - timedelta(days=back))["created"]
    made += _hand_made(today)
    return {"messages": QueuedMessage.objects.count(), "new_messages": made}


def _hand_made(today: date) -> int:
    if QueuedMessage.objects.filter(duplicate_key__startswith="demo:").exists():
        return 0
    clients = list(Client.objects.filter(status=Client.Status.ACTIVE).order_by("name")[:12])
    staff = list(User.objects.staff().filter(is_active=True).order_by("email")[:3])
    if not clients or not staff:
        return 0
    now = timezone.now()
    made = 0
    plan = [
        ("needs_approval", "Records for your year-end accounts", True, "Chasing records."),
        ("needs_approval", "Please check your company details", True, "Confirmation statement."),
        ("needs_approval", "Payroll changes for next month", False, "No address on file."),
        ("approved", "Your VAT return is due soon", True, "Approved, waiting to go."),
        ("sent", "Your accounts are ready to review", True, "Written by hand."),
        ("sent", "Thanks for the records", True, "Written by hand."),
        ("sent", "Corporation tax payment reminder", True, "Sent from a schedule."),
        ("failed", "Self assessment: information we need", True, "The mailbox was full."),
        ("cancelled", "A message that was not needed", True, "Cancelled by the manager."),
    ]
    for index, (state, subject, has_address, note) in enumerate(plan):
        client = clients[index % len(clients)]
        contact = services.main_contact(client)
        to = (contact.email if contact and has_address else "") or (
            "client@example.com" if has_address else ""
        )
        message = services.create_message(
            client,
            created_by=staff[index % len(staff)],
            to=to,
            subject=subject,
            body_html=f"<p>Dear {contact.first_name if contact else 'client'},</p>"
            f"<p>This is a made-up demo message about: {subject.lower()}.</p>",
            reason=note,
            duplicate_key=f"demo:{index}",
        )
        if state != "needs_approval":
            message.state = state
            message.approved_by = staff[(index + 1) % len(staff)]
            message.approved_at = now - timedelta(days=index)
            if state == "sent":
                message.sent_at = now - timedelta(days=index, hours=1)
                message.provider_message_id = f"demo-{index}"
                message.delivery_state = "delivered" if index != 5 else "bounced"
            if state == "failed":
                message.error = "The mailbox was full."
            message.save()
        made += 1
    return made
