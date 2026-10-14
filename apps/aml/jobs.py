"""Background jobs: AML review tasks and identity-document expiry notices."""

from datetime import time, timedelta

from django.utils import timezone

from apps import events
from apps.clients.models import Client
from apps.jobs.registry import Daily, register
from apps.onboarding import services as onboarding

from .models import IdentityCheck, RiskAssessment

REVIEW_LEAD_DAYS = 30
EXPIRY_LEAD_DAYS = 60


def create_review_tasks(today=None) -> int:
    """Thirty days before a review falls due, make the manager a task. Safe to run twice."""
    from apps.tasks.models import Task, TaskCategory, TaskKind
    from apps.tasks.services import create_task

    today = today or timezone.localdate()
    category = TaskCategory.objects.filter(name="AML").first()
    made = 0
    due = RiskAssessment.objects.filter(
        state=RiskAssessment.State.APPROVED,
        next_review_due__lte=today + timedelta(days=REVIEW_LEAD_DAYS),
        review_task_made=False,
    ).select_related("client")
    for assessment in due:
        client = assessment.client
        if client.status in (Client.Status.FORMER, Client.Status.LOST) or client.archived_at:
            continue
        create_task(
            None,
            title=f"AML review: {client.name}",
            client=client,
            kind=TaskKind.COMPLIANCE,
            category=category,
            owner=onboarding.responsible_user(client),
            target_date=assessment.next_review_due,
            due_date=assessment.next_review_due,
            source=Task.Source.GENERATED,
            description="<p>The client's anti-money-laundering review is coming up. "
            "Open the Risk tab and start a review.</p>",
        )
        assessment.review_task_made = True
        assessment.save(update_fields=["review_task_made", "updated_at"])
        made += 1
    return made


def notify_expiring_documents(today=None) -> int:
    """Sixty days before an identity document expires the manager is told. Once per date."""
    today = today or timezone.localdate()
    count = 0
    checks = (
        IdentityCheck.objects.filter(
            excluded=False,
            document_expiry__isnull=False,
            document_expiry__lte=today + timedelta(days=EXPIRY_LEAD_DAYS),
            expiry_notified_on__isnull=True,
        )
        .exclude(state=IdentityCheck.State.NOT_STARTED)
        .select_related("client", "contact")
    )
    for check in checks:
        client = check.client
        if client.status in (Client.Status.FORMER, Client.Status.LOST):
            continue
        onboarding.notify_staff(
            client,
            f"{check.contact.full_name}'s identity document for {client.name} expires on "
            f"{check.document_expiry:%d/%m/%Y}.",
            f"/clients/{client.pk}/risk/",
        )
        check.expiry_notified_on = today
        check.save(update_fields=["expiry_notified_on", "updated_at"])
        events.record(
            None,
            "aml.identity_expiring",
            f"{check.contact.full_name}'s identity document for {client.name} expires on "
            f"{check.document_expiry:%d/%m/%Y}.",
            client=client,
            target=check,
        )
        count += 1
    return count


@register(
    "aml_reviews",
    "AML reviews and identity expiry",
    Daily(time(6, 30)),
    description="Makes the manager an AML review task 30 days before a review is due, and "
    "notifies 60 days before an identity document expires. Safe to run twice.",
)
def aml_reviews(run):
    return {
        "review_tasks": create_review_tasks(),
        "expiry_notices": notify_expiring_documents(),
    }
