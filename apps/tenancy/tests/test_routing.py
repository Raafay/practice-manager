"""The web address chooses the practice; an unknown address reaches no practice."""

import pytest
from django.db import connection
from django.test import Client
from django_tenants.utils import schema_context

from apps.accounts.tests.factories import owner, sign_in
from apps.clients.tests.factories import ClientFactory
from apps.tenancy.models import Domain, Practice

pytestmark = pytest.mark.django_db


def test_each_address_reaches_its_own_practice(practice_a, practice_b):
    assert Domain.objects.get(domain="testserver").tenant == practice_a
    assert Domain.objects.get(domain="other.testserver").tenant == practice_b
    http = Client()
    http.get("/login/")
    assert connection.schema_name == "practice_a"
    http.get("/login/", HTTP_HOST="other.testserver")
    assert connection.schema_name == "practice_b"


@pytest.mark.parametrize("host", ["unknown.example.com", "testserver.example.com"])
def test_an_unknown_address_gets_a_plain_404(host, settings):
    settings.ALLOWED_HOSTS = ["*"]
    response = Client().get("/login/", HTTP_HOST=host)
    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/plain")
    assert response.content == b"Not found."
    assert response["X-Content-Type-Options"] == "nosniff"
    assert connection.schema_name == "public"


def test_an_address_outside_allowed_hosts_gets_a_plain_404():
    response = Client().get("/login/", HTTP_HOST="evil.example.com")
    assert response.status_code == 404
    assert response.content == b""


def test_an_address_of_the_public_schema_reaches_nothing():
    with schema_context("public"):
        public = Practice(schema_name="public", name="Platform")
        public.auto_create_schema = False
        public.save()
        Domain.objects.create(domain="platform.testserver", tenant=public, is_primary=True)
    response = Client().get("/login/", HTTP_HOST="platform.testserver")
    assert response.status_code == 404
    assert response.content == b"Not found."


def test_the_health_check_answers_on_any_address(settings):
    settings.ALLOWED_HOSTS = ["*"]
    response = Client().get("/healthz/", HTTP_HOST="internal-10-0-0-1")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_a_practice_sees_only_its_own_records(practice_b):
    ClientFactory(name="Only In A Ltd")
    user = owner()
    http = Client()
    sign_in(http, user)
    assert b"Only In A Ltd" in http.get("/clients/").content
    with schema_context("practice_b"):
        from apps.clients.models import Client as ClientRecord

        assert not ClientRecord.objects.filter(name="Only In A Ltd").exists()
    response = http.get("/clients/", HTTP_HOST="other.testserver")
    assert response.status_code == 302
    assert response["Location"].startswith("/login/")
