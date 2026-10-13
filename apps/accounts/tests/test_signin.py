import time

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.signals import SESSION_SEEN, SESSION_STARTED
from apps.core.models import PracticeSettings
from apps.events.models import ActivityEvent

from .factories import PASSWORD, add_totp, owner, portal_user, sign_in, staff, totp_code

pytestmark = pytest.mark.django_db

LOGIN = "/login/"


def post_login(client, email, password=PASSWORD, **extra):
    return client.post(LOGIN, {"login": email, "password": password}, **extra)


def signed_in_user(client):
    return client.get(reverse("overview")).wsgi_request.user


def test_login_page_is_our_own_wording(client):
    response = client.get(LOGIN)
    assert response.status_code == 200
    assert b"Staff sign-in" in response.content
    assert b"sign up" not in response.content.lower()


def test_sign_in_with_password_and_authenticator_code(client):
    user = staff()
    secret = add_totp(user)
    response = post_login(client, user.email)
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_authenticate")
    assert not signed_in_user(client).is_authenticated  # password alone is not enough

    response = client.post(reverse("mfa_authenticate"), {"code": totp_code(secret)})
    assert response.status_code == 302
    if response["Location"] == reverse("mfa_trust"):
        response = client.post(reverse("mfa_trust"), {"action": "skip"})
    assert signed_in_user(client) == user


def test_wrong_authenticator_code_does_not_sign_in(client):
    user = staff()
    add_totp(user)
    post_login(client, user.email)
    client.post(reverse("mfa_authenticate"), {"code": "123456"})
    assert not signed_in_user(client).is_authenticated


def test_sign_in_without_two_factor_is_sent_to_set_up_and_can_reach_nothing_else(client):
    user = staff()
    response = post_login(client, user.email)
    assert response.status_code == 302
    assert signed_in_user(client) == user

    setup = reverse("mfa_activate_totp")
    for url in ["/", "/settings/", "/profile/", "/styleguide/", "/notifications/", "/control/"]:
        response = client.get(url)
        assert response.status_code == 302, url
        assert response["Location"] == setup, url
    # HTMX requests get a redirect header instead.
    response = client.get("/settings/", headers={"HX-Request": "true"})
    assert response["HX-Redirect"] == setup

    assert client.get(setup).status_code == 200
    assert client.get(reverse("mfa_index")).status_code == 200


def test_after_setting_up_two_factor_the_app_opens(client, django_capture_on_commit_callbacks):
    user = staff()
    post_login(client, user.email)
    page = client.get(reverse("mfa_activate_totp"))
    secret = page.context["form"].secret
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(reverse("mfa_activate_totp"), {"code": totp_code(secret)})
    assert response.status_code == 302
    assert User.objects.get(pk=user.pk).mfa_done
    assert client.get("/").status_code == 200
    assert ActivityEvent.objects.filter(verb="auth.mfa_added", actor=user).exists()


def test_recovery_codes_need_the_password_again(client):
    from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes

    user = staff()
    sign_in(client, user, recent_password=False)
    RecoveryCodes.activate(user)
    response = client.get(reverse("mfa_view_recovery_codes"))
    assert response.status_code == 302
    assert "reauthenticate" in response["Location"]


def test_lockout_after_five_failures(client):
    user = staff()
    add_totp(user)
    for _ in range(5):
        response = post_login(client, user.email, "wrong-password-here")
    assert ActivityEvent.objects.filter(verb="auth.sign_in_failed").count() >= 5
    assert ActivityEvent.objects.filter(verb="auth.locked_out").exists()

    # Even the right password is refused for 15 minutes from this address.
    response = post_login(client, user.email)
    assert response.status_code == 429
    assert b"Too many failed sign-ins" in response.content
    assert not signed_in_user(client).is_authenticated


def test_lockout_is_per_address(client):
    user = staff()
    add_totp(user)
    for _ in range(5):
        post_login(client, user.email, "wrong-password-here", REMOTE_ADDR="203.0.113.5")
    response = post_login(client, user.email, REMOTE_ADDR="203.0.113.9")
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_authenticate")


def test_four_failures_do_not_lock(client):
    user = staff()
    add_totp(user)
    for _ in range(4):
        post_login(client, user.email, "wrong-password-here")
    response = post_login(client, user.email)
    assert response["Location"] == reverse("mfa_authenticate")


def test_deactivated_user_cannot_sign_in(client):
    user = staff(is_active=False)
    add_totp(user)
    response = post_login(client, user.email)
    assert not signed_in_user(client).is_authenticated
    assert response.status_code in {200, 302}
    if response.status_code == 302:
        assert response["Location"] != reverse("mfa_authenticate")


def test_deactivating_ends_an_open_session(client):
    user = staff()
    sign_in(client, user)
    assert client.get("/").status_code == 200
    User.objects.filter(pk=user.pk).update(is_active=False)
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith(LOGIN)


def test_portal_user_cannot_use_the_staff_sign_in(client):
    user = portal_user()
    response = post_login(client, user.email)
    assert response.status_code == 200
    assert not signed_in_user(client).is_authenticated
    assert ActivityEvent.objects.filter(verb="auth.sign_in_failed", actor_label=user.email).exists()


def test_session_ends_after_idle_limit(client):
    user = staff()
    sign_in(client, user)
    session = client.session
    session[SESSION_SEEN] = time.time() - 61 * 60
    session.save()
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith(LOGIN)
    assert not signed_in_user(client).is_authenticated
    assert ActivityEvent.objects.filter(verb="auth.session_expired").exists()


def test_session_ends_after_absolute_limit_even_when_active(client):
    user = staff()
    sign_in(client, user)
    session = client.session
    session[SESSION_STARTED] = time.time() - 12 * 3600 - 60
    session[SESSION_SEEN] = time.time()
    session.save()
    assert client.get("/").status_code == 302


def test_session_limits_follow_practice_settings(client):
    practice = PracticeSettings.load()
    practice.session_idle_minutes = 5
    practice.save()
    sign_in(client, staff())
    session = client.session
    session[SESSION_SEEN] = time.time() - 6 * 60
    session.save()
    assert client.get("/").status_code == 302


def test_trust_this_browser_is_offered_and_can_be_switched_off(client, settings):
    settings.MFA_TOTP_TOLERANCE = 1  # so two sign-ins can use two different codes
    user = staff()
    secret = add_totp(user)
    post_login(client, user.email)
    response = client.post(reverse("mfa_authenticate"), {"code": totp_code(secret, -1)})
    assert response["Location"] == reverse("mfa_trust")
    client.post(reverse("mfa_trust"), {"action": "trust"})
    assert signed_in_user(client) == user
    trust_cookie = {k: v.value for k, v in client.cookies.items() if "trust" in k}
    assert trust_cookie

    # A trusted browser skips the code next time.
    client.post(reverse("account_logout"))
    response = post_login(client, user.email)
    assert response["Location"] == "/"

    # The owner switches trust off: the code is asked for again, and no trust page.
    practice = PracticeSettings.load()
    practice.mfa_trust_enabled = False
    practice.save()
    client.post(reverse("account_logout"))
    response = post_login(client, user.email)
    assert response["Location"] == reverse("mfa_authenticate")
    response = client.post(reverse("mfa_authenticate"), {"code": totp_code(secret, 0)})
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert signed_in_user(client) == user


def test_sign_in_and_sign_out_are_recorded(client):
    user = owner()
    secret = add_totp(user)
    post_login(client, user.email)
    client.post(reverse("mfa_authenticate"), {"code": totp_code(secret)})
    client.post(reverse("mfa_trust"), {"action": "skip"})
    signed_in = ActivityEvent.objects.get(verb="auth.signed_in")
    assert signed_in.actor == user
    assert signed_in.ip_address == "127.0.0.1"

    client.post(reverse("account_logout"))
    assert ActivityEvent.objects.filter(verb="auth.signed_out", actor=user).exists()


def test_failed_sign_in_is_recorded_without_the_password(client):
    user = staff()
    post_login(client, user.email, "a-wrong-password-123")
    event = ActivityEvent.objects.get(verb="auth.sign_in_failed")
    assert event.actor is None
    assert event.actor_label == user.email
    assert "a-wrong-password-123" not in str(event.data) + event.summary
