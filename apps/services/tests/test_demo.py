import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.services.models import ClientService, Deadline, Service

pytestmark = pytest.mark.django_db


def test_demo_services_and_deadlines_are_a_spread_and_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = (ClientService.objects.count(), Deadline.objects.count())
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (ClientService.objects.count(), Deadline.objects.count())
    assert first[0] > 40 and first[1] > 40
    today = timezone.localdate()
    open_rows = Deadline.objects.filter(status="open")
    assert open_rows.filter(due_date__lt=today).exists()  # a few overdue
    assert open_rows.filter(due_date__gte=today, due_date__lte=today + timedelta(days=14)).exists()
    assert open_rows.filter(due_date__gt=today + timedelta(days=60)).exists()
    assert Deadline.objects.filter(status="done").exists()
    # services in every state, and every rule family is exercised
    assert set(ClientService.objects.values_list("state", flat=True)) == {
        "active",
        "proposed",
        "ended",
    }
    rules = set(Deadline.objects.values_list("rule", flat=True))
    assert {"ch_accounts", "vat_return", "payroll_run", "periodic"} <= rules
    assert Service.objects.count() == 18
