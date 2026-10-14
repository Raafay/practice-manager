"""Fixes from the Stage 13 security review (docs/SECURITY-REVIEW.md)."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import portal_user, sign_in, staff

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "name",
    ["account_change_password", "account_set_password", "mfa_activate_totp", "mfa_index"],
)
def test_portal_users_cannot_open_password_or_two_factor_pages(client, name):
    sign_in(client, portal_user())
    assert client.get(reverse(name)).status_code == 403
    assert client.post(reverse(name)).status_code == 403


def test_portal_users_can_still_sign_out_through_allauth(client):
    sign_in(client, portal_user())
    response = client.post(reverse("account_logout"))
    assert response.status_code == 302


def test_new_recovery_codes_can_be_made(client):
    """allauth locks the user row; the role join used to make PostgreSQL refuse."""
    user = staff()
    sign_in(client, user)
    response = client.post(reverse("mfa_generate_recovery_codes"))
    assert response.status_code in (200, 302)
    assert user.authenticator_set.filter(type="recovery_codes").exists()


# A person given users.manage cannot use it to gain more than they hold.


@pytest.fixture
def delegated_manager():
    from apps.accounts.tests.factories import manager

    person = manager()
    person.extra_rights = ["users.manage"]
    person.save()
    return person


def test_a_delegated_manager_cannot_make_themselves_owner(client, delegated_manager):
    from apps.accounts.models import Role

    sign_in(client, delegated_manager)
    owner_role = Role.objects.get(slug=Role.OWNER)
    client.post(reverse("accounts:user_role", args=[delegated_manager.pk]), {"role": owner_role.pk})
    delegated_manager.refresh_from_db()
    assert delegated_manager.role.slug == Role.MANAGER


def test_a_delegated_manager_cannot_grant_rights_they_lack(client, delegated_manager):
    sign_in(client, delegated_manager)
    colleague = staff()
    client.post(
        reverse("accounts:user_rights", args=[colleague.pk]),
        {"extra_rights": ["finance.owner"]},
    )
    colleague.refresh_from_db()
    assert colleague.extra_rights == []
    # Nor change their own.
    client.post(
        reverse("accounts:user_rights", args=[delegated_manager.pk]),
        {"extra_rights": ["users.manage", "audit.view"]},
    )
    delegated_manager.refresh_from_db()
    assert delegated_manager.extra_rights == ["users.manage"]


def test_a_delegated_manager_cannot_touch_an_owner(client, delegated_manager):
    from allauth.mfa.models import Authenticator

    from apps.accounts.tests.factories import add_totp, owner

    boss = owner()
    add_totp(boss)
    sign_in(client, delegated_manager)
    client.post(reverse("accounts:user_reset_mfa", args=[boss.pk]))
    assert Authenticator.objects.filter(user=boss).exists()
    client.post(reverse("accounts:user_deactivate", args=[boss.pk]))
    boss.refresh_from_db()
    assert boss.is_active


def test_a_delegated_manager_cannot_invite_an_owner_or_widen_a_role(client, delegated_manager):
    from apps.accounts.models import Invitation, Role

    sign_in(client, delegated_manager)
    response = client.post(
        reverse("accounts:invite"),
        {
            "name": "New Person",
            "email": "new.person@example.com",
            "role": Role.objects.get(slug=Role.OWNER).pk,
        },
    )
    assert response.status_code == 422
    assert not Invitation.objects.exists()
    data = {
        f"{role.slug}__{right}": "on"
        for role in Role.objects.exclude(slug=Role.OWNER)
        for right in role.rights
    }
    data["staff__finance.owner"] = "on"
    client.post(reverse("accounts:roles"), data)
    staff_role = Role.objects.get(slug=Role.STAFF)
    assert "finance.owner" not in staff_role.rights
    assert "fees.view" in staff_role.rights


def test_the_owner_still_can(client):
    from apps.accounts.models import Role
    from apps.accounts.tests.factories import owner

    sign_in(client, owner())
    colleague = staff()
    client.post(
        reverse("accounts:user_role", args=[colleague.pk]),
        {"role": Role.objects.get(slug=Role.OWNER).pk},
    )
    colleague.refresh_from_db()
    assert colleague.role.slug == Role.OWNER


# Wrong two-factor codes are limited per person, whatever address they come from.


def test_wrong_codes_from_many_addresses_lock_the_two_factor_step(client):
    from apps.accounts.tests.factories import PASSWORD, add_totp, totp_code
    from apps.events.models import ActivityEvent

    user = staff()
    secret = add_totp(user)
    for n in range(5):
        address = f"192.0.2.{n + 1}"
        client.post("/login/", {"login": user.email, "password": PASSWORD}, REMOTE_ADDR=address)
        client.post(reverse("mfa_authenticate"), {"code": "000001"}, REMOTE_ADDR=address)
    assert ActivityEvent.objects.filter(verb="auth.mfa_failed", target_id=user.pk).count() == 5
    client.post("/login/", {"login": user.email, "password": PASSWORD}, REMOTE_ADDR="192.0.2.99")
    response = client.post(
        reverse("mfa_authenticate"), {"code": totp_code(secret)}, REMOTE_ADDR="192.0.2.99"
    )
    assert b"Too many wrong codes" in response.content
    assert not client.get(reverse("overview")).wsgi_request.user.is_authenticated


# The visitor's address behind the host's proxy.


def _request(**meta):
    from django.test import RequestFactory

    return RequestFactory().get("/", **meta)


def test_without_a_trusted_proxy_the_forwarded_header_is_ignored(settings):
    from apps.core.ratelimit import client_ip

    settings.TRUSTED_PROXY_COUNT = 0
    settings.TRUSTED_CLIENT_IP_HEADER = ""
    request = _request(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9")
    assert client_ip(request) == "10.0.0.1"


def test_with_one_trusted_proxy_a_made_up_forwarded_entry_is_ignored(settings):
    from apps.core.ratelimit import client_ip

    settings.TRUSTED_PROXY_COUNT = 1
    settings.TRUSTED_CLIENT_IP_HEADER = ""
    # The visitor wrote "198.51.100.7"; the host's proxy appended the real address.
    request = _request(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.7, 203.0.113.9")
    assert client_ip(request) == "203.0.113.9"
    assert client_ip(_request(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="junk")) == "10.0.0.1"


def test_a_trusted_header_is_used_when_set(settings):
    from apps.core.ratelimit import client_ip

    settings.TRUSTED_CLIENT_IP_HEADER = "Fly-Client-IP"
    request = _request(REMOTE_ADDR="10.0.0.1", HTTP_FLY_CLIENT_IP="203.0.113.5")
    assert client_ip(request) == "203.0.113.5"


def test_lockout_and_the_activity_log_use_the_visitors_address(client, settings):
    from apps.events.models import ActivityEvent

    settings.TRUSTED_PROXY_COUNT = 1
    user = staff()
    client.post(
        "/login/",
        {"login": user.email, "password": "wrong-password-here"},
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR="203.0.113.77",
    )
    event = ActivityEvent.objects.filter(verb="auth.sign_in_failed").latest("pk")
    assert event.ip_address == "203.0.113.77"
