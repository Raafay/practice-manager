"""Made-up AML data for development: assessments at every level and review date.

Everything here is invented. Safe to run twice: a client that already has an
assessment is left alone.
"""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client

from . import services
from .models import RiskQuestion

# Answers that raise the score, by the start of the question text.
RAISERS = {
    "low": [],
    "medium": ["Does the business handle a lot of cash", "Is the business in a higher-risk sector"],
    "high": [
        "Is the ownership structure complex",
        "Does the business handle a lot of cash",
        "Is the business in a higher-risk sector",
        "Will we hold or move client money",
    ],
}

# (level, days until the next review). Negative means overdue.
PLAN = [
    ("low", 430),
    ("low", 300),
    ("medium", 150),
    ("low", -20),
    ("high", 12),
    ("medium", 200),
    ("low", 700),
    ("medium", 25),
    ("high", 330),
]


def build_post(level: str, today) -> dict:
    """A complete, made-up answer set that scores into the wanted level."""
    data = {"level": level}
    raisers = RAISERS[level]
    for question in RiskQuestion.objects.filter(active=True):
        risky = [o for o in question.options if o["score"] > 0]
        answer = next(o for o in question.options if o["score"] == 0)["value"]
        if risky and any(question.text.startswith(start) for start in raisers):
            answer = risky[0]["value"]
        data[f"q_{question.pk}"] = answer
        if question.records_check:
            data[f"d_{question.pk}"] = today.isoformat()
            data[f"h_{question.pk}"] = "Online search (demo)"
    return data


def assess(client: Client, level: str, assessor, approver=None, *, days_to_review=None):
    """Start and submit an assessment, and approve it if an approver is given."""
    today = timezone.localdate()
    assessment = services.start_assessment(assessor, client)
    problems = services.save_draft(assessor, assessment, build_post(level, today), submit=True)
    assert not problems, problems
    assessment.refresh_from_db()
    if approver is not None:
        assessment = services.approve(approver, assessment)
        if days_to_review is not None:
            assessment.next_review_due = today + timedelta(days=days_to_review)
            assessment.save(update_fields=["next_review_due", "updated_at"])
    return assessment


def seed() -> dict:
    boss = User.objects.filter(role__slug="owner", is_active=True).order_by("pk").first()
    manager = User.objects.filter(role__slug="manager", is_active=True).order_by("pk").first()
    if boss is None or manager is None:
        return {"assessments": 0}
    made = 0
    live = Client.objects.filter(status=Client.Status.ACTIVE, archived_at__isnull=True).order_by(
        "name"
    )
    for client, (level, days) in zip(live[: len(PLAN)], PLAN, strict=False):
        if client.risk_assessments.exists():
            continue
        assess(client, level, manager, boss, days_to_review=days)
        made += 1
    return {"assessments": made}
