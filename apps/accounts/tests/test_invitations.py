from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import Invitation, Role, User, hash_token
from apps.events.models import ActivityEvent

from .factories import manager, owner, sign_in, staff

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "correct horse battery staple"


def invite(client, boss, email="new.person@example.com"):
    sign_in(client, boss)
    response = client.post(
        reverse("accounts:invite"),
        {"name": "New Person", "email": email, "role": Role.objects.get(slug=Role.STAFF).pk},
    )
    assert response.status_code == 302
    body = mail.outbox[-1].body
    link = next(line for line in body.splitlines() if "/invite/" in line).strip()
    client.logout()
    return link.split("testserver", 1)[-1]


def test_owner_invites_and_the_email_goes_straight_out(client):
    path = invite(client, owner())
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["new.person@example.com"]
    assert path.startswith("/invite/")
    invitation = Invitation.objects.get()
    # Only the hash of the token is stored.
    token = path.rstrip("/").rsplit("/", 1)[-1]
    assert invitation.token_hash == hash_token(token)
    assert token not in invitation.token_hash
    assert ActivityEvent.objects.filter(verb="user.invited").exists()


def test_invitation_link_works_once(client):
    path = invite(client, owner())
    assert client.get(path).status_code == 200
    response = client.post(path, {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert response.status_code == 302
    assert response["Location"] == reverse("mfa_activate_totp")
    user = User.objects.get(email="new.person@example.com")
    assert user.role.slug == Role.STAFF
    assert user.check_password(NEW_PASSWORD)
    assert not user.mfa_done  # two-factor comes next

    client.logout()
    response = client.get(path)
    assert b"no longer works" in response.content
    response = client.post(
        path, {"password1": "another long password", "password2": "another long password"}
    )
    assert response.status_code == 410
    assert User.objects.filter(email="new.person@example.com").count() == 1


def test_invitation_link_expires_after_72_hours(client):
    path = invite(client, owner())
    invitation = Invitation.objects.get()
    assert invitation.expires_at - invitation.created_at == pytest.approx(
        timedelta(hours=72), abs=timedelta(seconds=5)
    )
    Invitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    response = client.get(path)
    assert b"expired" in response.content
    response = client.post(path, {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD})
    assert response.status_code == 410
    assert not User.objects.filter(email="new.person@example.com").exists()


def test_cancelled_invitation_stops_working(client):
    boss = owner()
    path = invite(client, boss)
    services.cancel_invitation(boss, Invitation.objects.get())
    assert b"cancelled" in client.get(path).content


def test_unknown_token_is_404(client):
    assert client.get("/invite/not-a-token/").status_code == 404


def test_short_password_is_refused(client):
    path = invite(client, owner())
    response = client.post(path, {"password1": "short", "password2": "short"})
    assert response.status_code == 422
    assert not User.objects.filter(email="new.person@example.com").exists()


def test_invite_refuses_an_email_already_in_use(client):
    boss = owner()
    taken = staff()
    sign_in(client, boss)
    response = client.post(
        reverse("accounts:invite"),
        {"name": "Dup", "email": taken.email.upper(), "role": Role.objects.get(slug=Role.STAFF).pk},
    )
    assert response.status_code == 422
    assert not mail.outbox


def test_invite_form_loads_as_a_partial_for_htmx(client):
    sign_in(client, owner())
    response = client.get(reverse("accounts:invite"), headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert b"<html" not in response.content
    assert b'id="invite-form"' in response.content


def test_only_the_owner_can_invite(client):
    sign_in(client, manager())
    response = client.post(
        reverse("accounts:invite"),
        {"name": "X", "email": "x@example.com", "role": Role.objects.get(slug=Role.STAFF).pk},
    )
    assert response.status_code == 403
    assert not Invitation.objects.exists()


def test_signed_in_person_cannot_accept(client):
    path = invite(client, owner())
    sign_in(client, staff())
    assert client.get(path).status_code == 409
