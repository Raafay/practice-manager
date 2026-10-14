"""Background jobs: HMRC authorisation expiry and engagement letter review tasks."""

from datetime import time

from django.utils import timezone

from apps.jobs.registry import Daily, register

from . import hmrc, letters
from . import services as onboarding


def create_letter_review_tasks(today=None) -> int:
    """Thirty days before a letter's review date, a task for the manager. Once per letter."""
    from apps.tasks.models import Task, TaskCategory, TaskKind
    from apps.tasks.services import create_task

    category = TaskCategory.objects.filter(name="Onboarding").first()
    made = 0
    for letter in letters.due_for_review(today):
        client = letter.client
        if client.status in ("former", "lost") or client.archived_at:
            continue
        create_task(
            None,
            title=f"Engagement letter review: {client.name}",
            client=client,
            kind=TaskKind.ONBOARDING,
            category=category,
            owner=onboarding.responsible_user(client),
            target_date=letter.review_due,
            due_date=letter.review_due,
            source=Task.Source.GENERATED,
            description="<p>The engagement letter is due for its yearly review. Check the "
            "services and fees, and prepare a new letter if they have changed.</p>",
        )
        letter.review_task_made = True
        letter.save(update_fields=["review_task_made", "updated_at"])
        made += 1
    return made


@register(
    "onboarding_daily",
    "HMRC authorisation expiry and letter reviews",
    Daily(time(6, 45)),
    description="Notifies the manager seven days before an HMRC request expires, marks "
    "expired ones, and makes a review task 30 days before an engagement letter is due for "
    "review. Safe to run twice.",
)
def onboarding_daily(run):
    result = hmrc.run_expiry(timezone.localdate())
    result["letter_review_tasks"] = create_letter_review_tasks()
    return result
