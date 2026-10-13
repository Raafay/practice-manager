"""Keep tasks in step with deadlines."""

from django.dispatch import receiver

from apps.services.deadlines import deadline_date_changed, deadlines_created
from apps.services.models import Deadline

from . import generation


@receiver(deadlines_created, sender=Deadline, dispatch_uid="tasks_deadlines_created")
def on_deadlines_created(sender, client, deadlines, actor=None, **kwargs):
    generation.create_for_deadlines(deadlines, actor=actor)


@receiver(deadline_date_changed, sender=Deadline, dispatch_uid="tasks_deadline_date_changed")
def on_deadline_date_changed(sender, deadline, old, new, actor=None, **kwargs):
    generation.sync_due_dates(deadline, old, new, actor=actor)
