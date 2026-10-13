"""Deny by default. Every address this project defines is checked here, so a view
added without a permission check fails the suite.
"""

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.tests.factories import owner, portal_user, sign_in, staff

pytestmark = pytest.mark.django_db

OUR_NAMESPACES = {"core", "accounts", "events"}
# Addresses open to the public, each with its own tests.
PUBLIC = {"accounts:accept_invitation"}
DUMMY_KWARGS = {"pk": 999999, "token": "not-a-real-token", "kind": "drawer"}


def our_url_names():
    names = ["overview"]

    def walk(patterns, namespace):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                walk(entry.url_patterns, entry.namespace or namespace)
            elif isinstance(entry, URLPattern) and namespace in OUR_NAMESPACES and entry.name:
                names.append(f"{namespace}:{entry.name}")

    walk(get_resolver().url_patterns, None)
    return sorted(set(names))


def _pattern_for(name):
    namespace, _, short = name.rpartition(":")

    def walk(patterns, ns):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                found = walk(entry.url_patterns, entry.namespace or ns)
                if found:
                    return found
            elif ns == (namespace or None) and entry.name == short:
                return entry
        return None

    return walk(get_resolver().url_patterns, None)


def url_for(name):
    """Reverse a URL name, filling any arguments with values that match nothing."""
    route = str(_pattern_for(name).pattern)
    kwargs = {key: DUMMY_KWARGS[key] for key in re.findall(r"<(?:\w+:)?(\w+)>", route)}
    return reverse(name, kwargs=kwargs or None)


STAFF_URLS = [name for name in our_url_names() if name not in PUBLIC]


def test_the_walk_finds_our_addresses():
    assert "accounts:users" in STAFF_URLS
    assert "events:audit_log" in STAFF_URLS
    assert "core:styleguide" in STAFF_URLS
    assert len(STAFF_URLS) > 20


@pytest.mark.parametrize("name", STAFF_URLS)
def test_signed_out_users_are_sent_to_sign_in(client, name):
    url = url_for(name)
    for method in (client.get, client.post):
        response = method(url)
        assert response.status_code == 302, (name, method)
        assert response["Location"].startswith(reverse("account_login")), name


@pytest.mark.parametrize("name", STAFF_URLS)
def test_portal_users_never_reach_staff_pages(client, name):
    sign_in(client, portal_user())
    url = url_for(name)
    assert client.get(url).status_code == 403, name
    assert client.post(url).status_code == 403, name


@pytest.mark.parametrize("name", STAFF_URLS)
def test_staff_without_two_factor_are_sent_to_set_it_up(client, name):
    sign_in(client, staff(), mfa=False)
    response = client.get(url_for(name))
    assert response.status_code == 302, name
    assert response["Location"] == reverse("mfa_activate_totp")


OWNER_ONLY = [
    "accounts:users",
    "accounts:invite",
    "accounts:teams",
    "accounts:team_create",
    "accounts:roles",
    "core:security_settings",
    "events:audit_log",
]


@pytest.mark.parametrize("name", OWNER_ONLY)
def test_the_wrong_role_gets_403(client, name):
    sign_in(client, staff())
    assert client.get(url_for(name)).status_code == 403


@pytest.mark.parametrize("name", OWNER_ONLY)
def test_the_owner_gets_in(client, name):
    sign_in(client, owner())
    assert client.get(url_for(name)).status_code == 200


def test_staff_pages_open_for_any_staff_member(client):
    sign_in(client, staff())
    for name in [
        "overview",
        "core:settings",
        "core:styleguide",
        "accounts:profile",
        "events:notifications",
    ]:
        assert client.get(url_for(name)).status_code == 200, name


def test_admin_is_owner_only_and_never_uses_its_own_password_page(client):
    response = client.get("/control/")
    assert response.status_code == 302
    login = client.get(response["Location"])
    assert login.status_code == 302
    assert login["Location"].startswith(reverse("account_login"))

    sign_in(client, staff())
    assert client.get("/control/", follow=True).status_code == 403

    client.logout()
    sign_in(client, owner())
    assert client.get("/control/").status_code == 200


def test_admin_refuses_an_owner_without_two_factor(client):
    sign_in(client, owner(), mfa=False)
    response = client.get("/control/")
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_activate_totp")


def test_signup_is_closed(client):
    response = client.post(
        "/signup/", {"email": "new@example.com", "password1": "x" * 20, "password2": "x" * 20}
    )
    from apps.accounts.models import User

    assert not User.objects.filter(email="new@example.com").exists()
    assert response.status_code in {200, 302}
