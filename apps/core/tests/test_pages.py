import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.core.models import PracticeSettings
from apps.events.models import ActivityEvent

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
INLINE_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
INLINE_HANDLER = re.compile(rb"\son[a-z]+\s*=", re.IGNORECASE)

PAGES = [
    "/",
    "/styleguide/",
    "/settings/",
    "/settings/users/",
    "/settings/teams/",
    "/settings/roles/",
    "/settings/audit/",
    "/settings/practice/",
    "/settings/security/",
    "/profile/",
    "/notifications/",
]


def test_every_page_has_the_csp_header_and_no_inline_scripts(client):
    sign_in(client, owner())
    for url in [*PAGES, "/2fa/", "/password/change/"]:
        response = client.get(url)
        assert response.status_code == 200, url
        assert "script-src 'self'" in response["Content-Security-Policy"], url
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Referrer-Policy"] == "same-origin"
        assert not INLINE_SCRIPT.search(response.content), url
        assert not INLINE_HANDLER.search(response.content), url


def test_sign_in_page_has_no_inline_scripts(client):
    response = client.get("/login/")
    assert not INLINE_SCRIPT.search(response.content)
    assert not INLINE_HANDLER.search(response.content)


def test_htmx_eval_is_off(client):
    sign_in(client, staff())
    content = client.get("/").content
    assert b'"allowEval": false' in content


def test_dates_show_as_dd_mm_yyyy(client):
    from datetime import date

    from django.template import Context, Template

    assert Template("{{ d|date }}").render(Context({"d": date(2026, 10, 13)})) == "13/10/2026"


class TestPracticeSettings:
    def test_manager_can_edit_details_and_it_is_recorded(self, client):
        sign_in(client, manager())
        response = client.post(
            reverse("core:practice_settings"),
            {
                "practice_name": "Example Practice",
                "accent_colour": "#112233",
                "vat_rate": "20.00",
                "vat_registered": "on",
            },
        )
        assert response.status_code == 302
        practice = PracticeSettings.load()
        assert practice.practice_name == "Example Practice"
        assert practice.vat_registered
        event = ActivityEvent.objects.get(verb="settings.changed")
        assert event.data["changes"]["practice_name"]["new"] == "Example Practice"

    def test_staff_cannot_edit(self, client):
        sign_in(client, staff())
        assert client.get(reverse("core:practice_settings")).status_code == 403

    @pytest.mark.parametrize("colour", ["red", "#12345", "#1234567", "#12345g", "url(x)"])
    def test_accent_colour_must_be_hex(self, client, colour):
        sign_in(client, owner())
        response = client.post(
            reverse("core:practice_settings"),
            {"practice_name": "X", "accent_colour": colour, "vat_rate": "20"},
        )
        assert response.status_code == 422
        assert PracticeSettings.load().accent_colour == "#2f5d8a"

    def test_logo_is_checked_and_served_only_to_staff(self, client):
        sign_in(client, owner())
        bad = SimpleUploadedFile("logo.png", b"not really a png", content_type="image/png")
        response = client.post(
            reverse("core:practice_settings"),
            {"practice_name": "X", "accent_colour": "#112233", "vat_rate": "20", "logo": bad},
        )
        assert response.status_code == 422

        good = SimpleUploadedFile("logo.png", PNG, content_type="image/png")
        client.post(
            reverse("core:practice_settings"),
            {"practice_name": "X", "accent_colour": "#112233", "vat_rate": "20", "logo": good},
        )
        practice = PracticeSettings.load()
        assert practice.logo.name.startswith("practice/")
        assert "logo" not in practice.logo.name  # the original name is not used
        response = client.get(reverse("core:practice_logo"))
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response["X-Content-Type-Options"] == "nosniff"

        client.logout()
        assert client.get(reverse("core:practice_logo")).status_code == 302

    def test_security_settings_are_owner_only_and_need_the_password(self, client):
        sign_in(client, manager())
        assert client.get(reverse("core:security_settings")).status_code == 403
        client.logout()
        sign_in(client, owner(), recent_password=False)
        response = client.post(
            reverse("core:security_settings"),
            {"session_idle_minutes": "30", "session_max_hours": "8"},
        )
        assert "reauthenticate" in response["Location"]
        assert PracticeSettings.load().session_idle_minutes == 60

    def test_security_settings_save(self, client):
        sign_in(client, owner())
        response = client.post(
            reverse("core:security_settings"),
            {"session_idle_minutes": "30", "session_max_hours": "8"},
        )
        assert response.status_code == 302
        practice = PracticeSettings.load()
        assert (
            practice.session_idle_minutes,
            practice.session_max_hours,
            practice.mfa_trust_enabled,
        ) == (30, 8, False)


@override_settings(DEBUG=False)
def test_error_pages_show_nothing_internal(client):
    sign_in(client, staff())
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"Traceback" not in response.content and b"urlpatterns" not in response.content

    response = client.get(reverse("accounts:users"))
    assert response.status_code == 403
    assert b"You do not have access" in response.content


def test_500_page_renders_without_a_database():
    from apps.core.views import server_error

    response = server_error(None)
    assert response.status_code == 500
    assert b"Something went wrong" in response.content
