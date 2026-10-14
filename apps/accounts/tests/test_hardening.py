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
