"""Overview panels: onboarding in progress, AML reviews due, authorisations expiring."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.aml import services as aml
from apps.aml.models import RiskAssessment
from apps.clients.models import Client

from . import hmrc
from . import services as onboarding

REVIEW_WINDOW_DAYS = 30
LIMIT = 8


def onboarding_in_progress():
    rows = []
    clients = Client.objects.not_archived().filter(status=Client.Status.ONBOARDING)
    for client in clients.prefetch_related("onboarding_items").order_by("name"):
        progress = onboarding.progress(client)
        rows.append({"client": client, **progress})
    return rows


def aml_reviews_due(today=None):
    today = today or timezone.localdate()
    cutoff = today + timedelta(days=REVIEW_WINDOW_DAYS)
    rows = []
    due = (
        RiskAssessment.objects.filter(
            state=RiskAssessment.State.APPROVED, next_review_due__lte=cutoff
        )
        .exclude(client__status__in=(Client.Status.FORMER, Client.Status.LOST))
        .filter(client__archived_at__isnull=True)
        .select_related("client")
        .order_by("next_review_due")
    )
    for assessment in due:
        rows.append(
            {
                "client": assessment.client,
                "due": assessment.next_review_due,
                "overdue": assessment.next_review_due < today,
                "level": assessment.level,
            }
        )
    awaiting = RiskAssessment.objects.filter(state=RiskAssessment.State.SUBMITTED).select_related(
        "client"
    )
    return rows, [a.client for a in awaiting]


def authorisations_expiring(today=None):
    today = today or timezone.localdate()
    rows = []
    for auth in hmrc.expiring(today).order_by("client__name"):
        rows.append({"auth": auth, "date": auth.link_expires_on or auth.code_expires_on})
    rows.sort(key=lambda r: r["date"])
    return rows


def overview_context(user) -> dict:
    reviews, awaiting = aml_reviews_due()
    onboarding_rows = onboarding_in_progress()
    expiring = authorisations_expiring()
    return {
        "onboarding_rows": onboarding_rows[:LIMIT],
        "onboarding_total": len(onboarding_rows),
        "review_rows": reviews[:LIMIT],
        "review_total": len(reviews),
        "awaiting_approval": awaiting if user.can("aml.approve") else [],
        "expiring_rows": expiring[:LIMIT],
        "expiring_total": len(expiring),
        "aml_state": aml.state_of,
    }
