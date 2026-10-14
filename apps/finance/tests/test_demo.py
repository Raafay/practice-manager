import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import sign_in
from apps.finance import invoicing
from apps.finance.models import Target, XeroConnection, XeroContact, XeroInvoice
from apps.timekeeping.models import TimeEntry

pytestmark = pytest.mark.django_db


def test_demo_gives_every_finance_page_figures_and_is_safe_to_run_twice(client):
    call_command("seed_demo", stdout=io.StringIO())
    first = (
        TimeEntry.objects.count(),
        XeroInvoice.objects.count(),
        XeroContact.objects.count(),
        Target.objects.count(),
    )
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (
        TimeEntry.objects.count(),
        XeroInvoice.objects.count(),
        XeroContact.objects.count(),
        Target.objects.count(),
    )
    assert first[0] > 500 and first[1] > 50 and first[3] == 12
    # No connection is made up, so the nightly sync never calls Xero with a fake token.
    assert not XeroConnection.objects.exists()
    assert invoicing.overdue_groups() and invoicing.check_fee()
    assert XeroContact.objects.filter(client__isnull=True).exists()  # something to match

    boss = User.objects.get(email="morgan.hale@example.com")
    sign_in(client, boss)
    for name in ("fees", "invoices", "targets", "forecast", "summary", "matching", "settings"):
        assert client.get(reverse(f"finance:{name}")).status_code == 200, name
    assert client.get(reverse("overview")).status_code == 200
    assert client.get(reverse("timekeeping:sheet")).status_code == 200
