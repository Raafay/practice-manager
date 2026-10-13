import io

import pytest
from allauth.mfa.models import Authenticator
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.accounts.models import Role, Team, User
from apps.events.models import ActivityEvent, Notification

from .factories import TeamFactory, add_totp, owner, sign_in, staff

pytestmark = pytest.mark.django_db


def test_users_page_lists_staff_and_two_factor_state(client):
    boss = owner(name="Una Owner")
    staff(name="Pat Nofactor")
    sign_in(client, boss)
    response = client.get(reverse("accounts:users"))
    assert b"Una Owner" in response.content
    assert b"Pat Nofactor" in response.content
    assert b"Not set up" in response.content


def test_reset_two_factor(client):
    boss, person = owner(), staff()
    add_totp(person)
    sign_in(client, boss)
    response = client.post(reverse("accounts:user_reset_mfa", args=[person.pk]))
    assert response.status_code == 302
    assert not Authenticator.objects.filter(user=person).exists()
    assert ActivityEvent.objects.filter(verb="user.mfa_reset", target_id=str(person.pk)).exists()


def test_deactivate_and_reactivate(client):
    boss, person = owner(), staff()
    sign_in(client, boss)
    client.post(reverse("accounts:user_deactivate", args=[person.pk]))
    person.refresh_from_db()
    assert not person.is_active
    assert person.deactivated_at is not None
    client.post(reverse("accounts:user_reactivate", args=[person.pk]))
    person.refresh_from_db()
    assert person.is_active
    verbs = set(ActivityEvent.objects.values_list("verb", flat=True))
    assert {"user.deactivated", "user.reactivated"} <= verbs


def test_cannot_deactivate_yourself(client):
    first = owner()
    owner()
    sign_in(client, first)
    response = client.post(reverse("accounts:user_deactivate", args=[first.pk]), follow=True)
    assert b"cannot deactivate your own account" in response.content
    first.refresh_from_db()
    assert first.is_active


def test_teams(client):
    boss, person = owner(), staff()
    sign_in(client, boss)
    response = client.post(
        reverse("accounts:team_create"),
        {"name": "Compliance", "description": "", "members": [person.pk]},
    )
    assert response.status_code == 302
    team = Team.objects.get(name="Compliance")
    assert list(team.members.all()) == [person]
    client.post(
        reverse("accounts:team_edit", args=[team.pk]),
        {"name": "Tax", "description": "x", "members": []},
    )
    team.refresh_from_db()
    assert team.name == "Tax" and not team.members.exists()
    client.post(reverse("accounts:team_delete", args=[team.pk]))
    assert not Team.objects.exists()
    verbs = list(
        ActivityEvent.objects.filter(verb__startswith="team.").values_list("verb", flat=True)
    )
    assert sorted(verbs) == ["team.changed", "team.created", "team.deleted"]


def test_set_user_teams(client):
    boss, person = owner(), staff()
    team = TeamFactory(name="Advisory")
    sign_in(client, boss)
    client.post(reverse("accounts:user_teams", args=[person.pk]), {"teams": [team.pk]})
    assert list(person.teams.all()) == [team]
    assert ActivityEvent.objects.filter(verb="user.teams_changed").exists()


def test_profile_edit_is_recorded(client):
    person = staff(name="Before Name")
    sign_in(client, person)
    response = client.post(
        reverse("accounts:profile"),
        {
            "name": "After Name",
            "initials": "an",
            "colour": "#123456",
            "job_title": "Bookkeeper",
            "weekly_hours": "30",
            "email_signature": "",
        },
    )
    assert response.status_code == 302
    person.refresh_from_db()
    assert person.name == "After Name"
    assert person.initials == "AN"
    event = ActivityEvent.objects.get(verb="user.profile_changed")
    assert event.data["changes"]["name"] == {"old": "Before Name", "new": "After Name"}


def test_profile_rejects_a_bad_colour_and_initials(client):
    person = staff()
    sign_in(client, person)
    response = client.post(
        reverse("accounts:profile"),
        {
            "name": "X",
            "initials": "ABC",
            "colour": "red",
            "job_title": "",
            "weekly_hours": "30",
            "email_signature": "",
        },
    )
    assert response.status_code == 422


def test_create_owner_command(monkeypatch):
    monkeypatch.setenv("OWNER_PW", "a strong owner password")
    out = io.StringIO()
    call_command(
        "create_owner",
        "--email",
        "Boss@Example.com",
        "--name",
        "Boss Person",
        "--password-from-env",
        "OWNER_PW",
        stdout=out,
    )
    user = User.objects.get(email="boss@example.com")
    assert user.is_owner
    assert user.check_password("a strong owner password")
    assert not user.mfa_done


def test_create_owner_refuses_a_weak_password(monkeypatch):
    monkeypatch.setenv("OWNER_PW", "short")
    with pytest.raises(CommandError):
        call_command(
            "create_owner",
            "--email",
            "b@example.com",
            "--name",
            "B",
            "--password-from-env",
            "OWNER_PW",
        )


def test_seed_demo_is_safe_to_run_twice():
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    call_command("seed_demo", stdout=out)
    assert User.objects.staff().count() == 5
    assert User.objects.active_owners().count() == 1
    assert User.objects.filter(role__slug=Role.MANAGER).count() == 1
    assert User.objects.filter(role__slug=Role.STAFF).count() == 3
    assert Team.objects.count() == 2
    assert all(user.mfa_done for user in User.objects.staff())
    assert Notification.objects.count() == 5
    assert "demo-password-2026" in out.getvalue()


def test_seed_demo_refused_where_demo_data_is_not_allowed(settings):
    settings.DEBUG = False
    settings.ALLOW_DEMO_DATA = False
    with pytest.raises(CommandError):
        call_command("seed_demo")


def test_dev_login_only_with_debug(settings):
    person = staff()
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("dev_login", person.email)


def test_dev_login_creates_a_signed_in_session(settings, client):
    person = staff()
    settings.DEBUG = True
    out = io.StringIO()
    call_command("dev_login", person.email, stdout=out)
    client.cookies["sessionid"] = out.getvalue().strip()
    response = client.get("/")
    assert response.status_code == 200
    assert response.wsgi_request.user == person
