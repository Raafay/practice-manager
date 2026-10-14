"""Sign-in by emailed code (spec 01 section 4)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import staff
from apps.portal import signin
from apps.portal.models import PortalLoginCode
from apps.portal.tests.helpers import portal_person

pytestmark = pytest.mark.django_db


def ask_for_code(client, email):
    return client.post(reverse("portal:login"), {"email": email})


def code_from_mail() -> str:
    body = mail.outbox[-1].body
    return body.split("code is ")[1][:6]


def enter(client, code):
    return client.post(reverse("portal:login_code"), {"code": code})


def test_the_right_code_signs_in(client):
    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    response = enter(client, code_from_mail())
    assert response.status_code == 302 and response.url == reverse("portal:home")
    assert client.get(reverse("portal:home")).status_code == 200


def test_a_wrong_code_is_refused(client):
    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    response = enter(client, "000000" if code_from_mail() != "000000" else "111111")
    assert response.status_code == 422
    assert client.get(reverse("portal:home")).status_code == 302  # still signed out


def test_an_expired_code_is_refused(client):
    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    code = code_from_mail()
    PortalLoginCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert enter(client, code).status_code == 422


def test_a_code_lasts_ten_minutes():
    assert signin.CODE_MINUTES == 10 and signin.MAX_TRIES == 5


def test_five_wrong_tries_lock_the_code(client):
    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    right = code_from_mail()
    wrong = "123456" if right != "123456" else "654321"
    for _ in range(5):
        assert enter(client, wrong).status_code == 422
    assert enter(client, right).status_code == 422  # even the right one now


def test_a_used_code_cannot_be_used_twice(client):
    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    code = code_from_mail()
    assert enter(client, code).status_code == 302
    client.post(reverse("portal:logout"))
    ask_for_code(client, "nobody@example.com")
    assert enter(client, code).status_code == 422


def test_unknown_and_known_emails_get_the_same_page(client):
    user, _, _ = portal_person()
    known = ask_for_code(client, user.email)
    unknown = ask_for_code(client, "stranger@example.com")
    assert known.status_code == unknown.status_code == 200
    for response in (known, unknown):
        text = response.content.decode()
        assert "code is on its way" in text
        assert "stranger@example.com" not in text and user.email not in text
    assert [t.name for t in known.templates if t.name] == [
        t.name for t in unknown.templates if t.name
    ]
    assert len(mail.outbox) == 1  # only the real person got an email


def test_a_staff_email_is_not_offered_a_code(client):
    person = staff()
    response = ask_for_code(client, person.email)
    assert response.status_code == 200
    assert len(mail.outbox) == 0
    assert PortalLoginCode.objects.count() == 0


def test_a_withdrawn_contact_is_not_sent_a_code(client):
    user, _, link = portal_person()
    link.portal_access = False
    link.save()
    ask_for_code(client, user.email)
    assert len(mail.outbox) == 0


def test_code_requests_are_rate_limited(client):
    user, _, _ = portal_person()
    for _ in range(7):
        ask_for_code(client, user.email)
    assert len(mail.outbox) == 5


def test_a_staff_account_cannot_use_the_portal(client):
    from apps.accounts.tests.factories import sign_in

    sign_in(client, staff())
    assert client.get(reverse("portal:home")).status_code == 403
    assert client.post(reverse("portal:login"), {"email": "x@example.com"}).status_code == 403


def test_the_staff_sign_in_refuses_a_portal_account(client):
    user, _, _ = portal_person()
    user.set_password("a-long-test-password")
    user.save()
    response = client.post(
        reverse("account_login"), {"login": user.email, "password": "a-long-test-password"}
    )
    assert response.status_code == 200
    assert client.get(reverse("portal:home")).status_code == 302


def test_portal_session_limits(settings):
    assert settings.PORTAL_SESSION_IDLE_MINUTES == 30
    assert settings.PORTAL_SESSION_MAX_HOURS == 8


def test_an_idle_portal_session_ends_at_the_portal_sign_in(client):
    import time

    user, _, _ = portal_person()
    ask_for_code(client, user.email)
    enter(client, code_from_mail())
    session = client.session
    session["pm_seen_at"] = time.time() - 31 * 60
    session.save()
    response = client.get(reverse("portal:home"))
    assert response.status_code == 302 and response.url == reverse("portal:login")


def test_signing_out(client):
    user, _, _ = portal_person()
    client.force_login(user)
    assert client.post(reverse("portal:logout")).status_code == 302
    assert client.get(reverse("portal:home")).status_code == 302
