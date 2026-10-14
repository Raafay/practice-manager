"""Requests through the app with the production security settings switched on."""

from unittest import mock

import pytest
from django.test import override_settings

from apps.core.headers import header_problems
from apps.core.tests.test_prod_settings import load_prod

pytestmark = pytest.mark.django_db

SECURITY_NAMES = (
    "SECURE_SSL_REDIRECT",
    "SECURE_REDIRECT_EXEMPT",
    "SECURE_PROXY_SSL_HEADER",
    "SECURE_HSTS_SECONDS",
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
    "CSRF_COOKIE_HTTPONLY",
    "SESSION_COOKIE_HTTPONLY",
    "SESSION_COOKIE_SAMESITE",
    "CSRF_COOKIE_SAMESITE",
    "SECURE_REFERRER_POLICY",
    "SECURE_CONTENT_TYPE_NOSNIFF",
    "X_FRAME_OPTIONS",
    "CONTENT_SECURITY_POLICY",
)


@pytest.fixture
def prod_security(monkeypatch):
    prod = load_prod(monkeypatch)
    with override_settings(**{name: getattr(prod, name) for name in SECURITY_NAMES}):
        yield


def _cookies(response):
    return [morsel.OutputString() for morsel in response.cookies.values()]


def test_headers_and_cookies_with_production_settings(client, prod_security):
    response = client.get("/login/", secure=True)
    assert response.status_code == 200
    assert header_problems(response.headers, _cookies(response)) == []
    assert "csrftoken" in response.cookies


def test_plain_http_is_sent_to_https(client, prod_security):
    response = client.get("/login/")
    assert response.status_code == 301
    assert response["Location"].startswith("https://")


def test_the_health_check_answers_over_plain_http_and_any_host(client, prod_security):
    response = client.get("/healthz/", HTTP_HOST="10.1.2.3:8000")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_the_header_check_spots_a_missing_header():
    problems = header_problems({"X-Frame-Options": "DENY"}, ["sessionid=x; Path=/"])
    assert any("Strict-Transport-Security" in p for p in problems)
    assert any("not marked Secure" in p for p in problems)


def test_the_health_check_says_when_the_database_is_down(client):
    with mock.patch("django.db.backends.utils.CursorWrapper.execute", side_effect=Exception):
        response = client.get("/healthz/")
    assert response.status_code == 503
