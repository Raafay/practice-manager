"""The client summary PDF: details, people, services, open deadlines, open tasks, recent activity.

Fees show only for people with `fees.view`. Tax references and other encrypted values are
never included, and no document is attached.
"""

from django.template.loader import render_to_string
from django.utils import timezone

from apps import events
from apps.aml.services import state_of
from apps.comms.letters import render_pdf
from apps.core.models import PracticeSettings
from apps.events.models import ActivityEvent
from apps.services.fees import totals
from apps.services.models import ClientService
from apps.tasks.models import Task

RECENT_EVENTS = 15


def context(client, user) -> dict:
    fees = user.can("fees.view")
    services = list(
        client.client_services.exclude(state=ClientService.State.ENDED).select_related("service")
    )
    monthly, one_off = totals(services) if fees else (None, None)
    return {
        "client": client,
        "fees": fees,
        "aml_state": state_of(client)[1],
        "links": client.client_contacts.filter(resigned_on__isnull=True).select_related("contact"),
        "services": services,
        "monthly_total": monthly,
        "one_off_total": one_off,
        "deadlines": client.deadlines.open().order_by("due_date")[:40],
        "tasks": Task.objects.open()
        .filter(client=client)
        .select_related("owner", "status")
        .order_by("due_date", "target_date", "title")[:40],
        "events": ActivityEvent.objects.filter(client=client).order_by("-created_at")[
            :RECENT_EVENTS
        ],
        "generated_by": user,
        "generated_at": timezone.localtime(),
    }


def build_pdf(client, user) -> bytes:
    body = render_to_string("reports/client_summary_pdf.html", context(client, user))
    pdf = render_pdf(body, PracticeSettings.load())
    events.record(
        user,
        "report.client_summary",
        f"{user} generated a summary report for {client.name}.",
        client=client,
        target=client,
        with_fees=user.can("fees.view"),
    )
    return pdf
