import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.tasks.models import Task, TaskComment, TaskKind

pytestmark = pytest.mark.django_db


def test_demo_tasks_are_a_spread_and_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = Task.objects.count()
    call_command("seed_demo", stdout=io.StringIO())
    assert first == Task.objects.count()
    today = timezone.localdate()
    advisory = Task.objects.filter(kind=TaskKind.ADVISORY)
    assert advisory.count() == 25
    assert advisory.filter(owner__isnull=True).exists()
    assert advisory.filter(target_date__lt=today, status__is_done=False).exists()
    assert advisory.filter(steps__done_at__isnull=False).exists()
    assert TaskComment.objects.exists()
    assert len(set(advisory.values_list("category", flat=True))) >= 8
    compliance = Task.objects.filter(kind=TaskKind.COMPLIANCE)
    assert compliance.filter(status__is_done=True).exists()
    assert (
        compliance.filter(status__is_done=False, due_date__lt=today).exists()
        or compliance.filter(
            status__is_done=False, due_date__lte=today + timedelta(days=14)
        ).exists()
    )
    assert not Task.objects.filter(deadline__status="done", status__is_done=False).exists()
