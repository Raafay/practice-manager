import io

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.tests.factories import sign_in, staff
from apps.clients.models import Client
from apps.companieshouse.models import CompanySnapshot
from apps.jobs.models import JobRun

pytestmark = pytest.mark.django_db


def test_demo_companies_get_snapshots_once(client):
    call_command("seed_demo", stdout=io.StringIO())
    companies = Client.objects.exclude(company_number="")
    assert companies.exists()
    assert CompanySnapshot.objects.count() == companies.count()
    runs = JobRun.objects.count()
    call_command("seed_demo", stdout=io.StringIO())
    assert CompanySnapshot.objects.count() == companies.count()
    assert JobRun.objects.count() == runs
    sign_in(client, staff())
    first = companies.order_by("pk").first()
    page = client.get(reverse("companieshouse:tab", args=[first.pk])).content.decode()
    assert "Recent filings" in page and "Resigned" in page
