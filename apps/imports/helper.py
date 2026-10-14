"""Migration helper: clear deadlines that were already dealt with before the move.

After services are imported, deadlines are created for recent periods. Those already
filed in the old system show here, grouped by rule, to be marked done in one go.
"""

from datetime import timedelta
from itertools import groupby

from django.db import transaction
from django.utils import timezone

from apps import events
from apps.services import deadlines as deadline_services
from apps.services.models import Deadline
from apps.tasks import services as task_services

from .services import require_import, who

WITHIN_DAYS = 30
DONE_NOTE = "Already dealt with before the move to this system."


def open_recent(today=None):
    """Open deadlines that are overdue or due in the next 30 days."""
    today = today or timezone.localdate()
    return (
        Deadline.objects.open()
        .filter(client__archived_at__isnull=True, due_date__lte=today + timedelta(days=WITHIN_DAYS))
        .select_related("client", "client_service__service")
        .order_by("rule", "due_date", "client__name", "pk")
    )


def groups(today=None) -> list[tuple[str, list[Deadline]]]:
    """[(rule title, deadlines)] in rule title order."""
    rows = list(open_recent(today))
    rows.sort(key=lambda d: (d.rule_title, d.due_date, d.client.name))
    return [(title, list(items)) for title, items in groupby(rows, key=lambda d: d.rule_title)]


def mark_already_done(actor, ids, *, complete_tasks: bool, today=None) -> int:
    """Mark the ticked deadlines done. Only ones the helper lists can be marked."""
    require_import(actor)
    chosen = list(open_recent(today).filter(pk__in=[int(i) for i in ids if str(i).isdigit()]))
    tasks_done = 0
    with transaction.atomic():
        for deadline in chosen:
            deadline_services.mark_done(actor, deadline, note=DONE_NOTE)
            if complete_tasks:
                for task in deadline.tasks.filter(
                    completed_at__isnull=True, cancelled_at__isnull=True
                ):
                    task_services.complete(actor, task)
                    tasks_done += 1
        if chosen:
            events.record(
                actor,
                "import.deadlines_cleared",
                f"{who(actor)} marked {len(chosen)} deadline{'s' if len(chosen) != 1 else ''} "
                "as already done before the move"
                + (f", and completed {tasks_done} of their tasks." if tasks_done else "."),
                deadlines=len(chosen),
                tasks=tasks_done,
            )
    return len(chosen)
