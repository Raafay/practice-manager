import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import LastOwnerError, Role, User
from apps.accounts.rights import RIGHTS, UnknownRight
from apps.events.models import ActivityEvent

from .factories import manager, owner, portal_user, sign_in, staff

pytestmark = pytest.mark.django_db

# The table in docs/specs/01-security-and-users.md section 2, with CORRECTIONS 16.
EXPECTED = {
    "fees.view": ("yes", "yes", "yes"),
    "finance.owner": ("yes", "no", "no"),
    "aml.approve": ("yes", "no", "no"),
    "documents.sensitive": ("yes", "yes", "yes"),
    "comms.approve": ("yes", "yes", "yes"),
    "comms.approve_fees": ("yes", "yes", "no"),
    "settings.manage": ("yes", "yes", "no"),
    "users.manage": ("yes", "no", "no"),
    "data.export": ("yes", "yes", "no"),
    "data.import": ("yes", "no", "no"),
    "clients.archive": ("yes", "yes", "no"),
    "clients.delete": ("yes", "no", "no"),
    "onboarding.override": ("yes", "no", "no"),
    "integrations.manage": ("yes", "no", "no"),
    "audit.view": ("yes", "no", "no"),
    "comms.pause": ("yes", "yes", "no"),
    "clients.status": ("yes", "yes", "no"),
    "time.edit_all": ("yes", "yes", "no"),
    "system.view": ("yes", "no", "no"),
    "retention.manage": ("yes", "no", "no"),
}


def test_the_expected_table_covers_every_right():
    assert set(EXPECTED) == set(RIGHTS)


@pytest.mark.parametrize("right", sorted(EXPECTED))
def test_each_seeded_role_has_the_rights_in_the_table(right):
    roles = {role.slug: role for role in Role.objects.all()}
    assert set(roles) == {"owner", "manager", "staff"}
    expected = dict(zip(("owner", "manager", "staff"), EXPECTED[right], strict=True))
    for slug, answer in expected.items():
        assert roles[slug].has(right) is (answer == "yes"), (slug, right)


@pytest.mark.parametrize(
    ("make", "right", "allowed"),
    [
        (owner, "finance.owner", True),
        (manager, "settings.manage", True),
        (manager, "users.manage", False),
        (staff, "fees.view", True),
        (staff, "data.export", False),
    ],
)
def test_user_can_follows_the_role(make, right, allowed):
    assert make().can(right) is allowed


def test_user_can_with_a_per_user_grant():
    person = staff()
    assert not person.can("data.export")
    services.set_extra_rights(owner(), person, ["data.export"])
    person.refresh_from_db()
    assert person.can("data.export")
    assert not person.can("data.import")
    assert "data.export" in person.effective_rights()


def test_a_grant_is_recorded():
    boss, person = owner(), staff()
    services.set_extra_rights(boss, person, ["data.export"])
    event = ActivityEvent.objects.get(verb="user.rights_changed")
    assert event.actor == boss
    assert event.data["added"] == ["data.export"]


def test_unknown_right_names_raise():
    with pytest.raises(UnknownRight):
        staff().can("fees.veiw")


def test_inactive_and_portal_users_hold_no_rights():
    assert not staff(is_active=False).can("fees.view")
    assert not portal_user().can("fees.view")
    assert portal_user().effective_rights() == set()


def test_only_users_manage_may_change_roles():
    with pytest.raises(PermissionDenied):
        services.change_role(manager(), staff(), Role.objects.get(slug=Role.MANAGER))


def test_role_change_is_recorded():
    boss, person = owner(), staff()
    services.change_role(boss, person, Role.objects.get(slug=Role.MANAGER))
    person.refresh_from_db()
    assert person.role.slug == Role.MANAGER
    event = ActivityEvent.objects.get(verb="user.role_changed")
    assert event.actor == boss
    assert event.target == person
    assert event.data["role"] == {"old": "Staff", "new": "Manager"}


class TestLastOwner:
    def test_last_owner_cannot_be_demoted(self):
        boss = owner()
        with pytest.raises(LastOwnerError):
            services.change_role(boss, boss, Role.objects.get(slug=Role.STAFF))
        boss.refresh_from_db()
        assert boss.role.slug == Role.OWNER

    def test_last_owner_cannot_be_deactivated(self):
        boss = owner()
        with pytest.raises(LastOwnerError):
            boss.is_active = False
            boss.save()

    def test_last_owner_cannot_be_deactivated_by_another_owner_once_alone(self):
        first, second = owner(), owner()
        services.deactivate_user(first, second)
        with pytest.raises(ValidationError):
            services.deactivate_user(first, first)  # nobody deactivates themselves
        assert User.objects.active_owners().count() == 1

    def test_last_owner_cannot_be_deleted(self):
        boss = owner()
        with pytest.raises(LastOwnerError):
            boss.delete()
        assert User.objects.filter(pk=boss.pk).exists()

    def test_an_owner_can_be_demoted_when_another_exists(self):
        first, second = owner(), owner()
        services.change_role(first, second, Role.objects.get(slug=Role.MANAGER))
        second.refresh_from_db()
        assert second.role.slug == Role.MANAGER

    def test_the_users_page_shows_the_error_instead_of_failing(self, client):
        boss = owner()
        sign_in(client, boss)
        response = client.post(
            reverse("accounts:user_role", args=[boss.pk]),
            {"role": Role.objects.get(slug=Role.STAFF).pk},
            follow=True,
        )
        assert response.status_code == 200
        assert b"one active owner" in response.content
        boss.refresh_from_db()
        assert boss.role.slug == Role.OWNER


def test_owner_role_rights_cannot_be_changed():
    with pytest.raises(ValidationError):
        services.set_role_rights(owner(), Role.objects.get(slug=Role.OWNER), [])


def test_roles_page_saves_ticks_and_records_them(client):
    boss = owner()
    sign_in(client, boss)
    data = {f"staff__{right}": "on" for right in ["fees.view", "comms.approve", "data.export"]}
    data.update({f"manager__{right}": "on" for right in Role.objects.get(slug="manager").rights})
    response = client.post(reverse("accounts:roles"), data)
    assert response.status_code == 302
    staff_role = Role.objects.get(slug=Role.STAFF)
    assert set(staff_role.rights) == {"fees.view", "comms.approve", "data.export"}
    event = ActivityEvent.objects.get(verb="role.rights_changed")
    assert event.data == {"added": ["data.export"], "removed": ["documents.sensitive"]}


def test_changing_roles_asks_for_the_password_again(client):
    boss, person = owner(), staff()
    sign_in(client, boss, recent_password=False)
    response = client.post(
        reverse("accounts:user_role", args=[person.pk]),
        {"role": Role.objects.get(slug=Role.MANAGER).pk},
    )
    assert response.status_code == 302
    assert "reauthenticate" in response["Location"]
    person.refresh_from_db()
    assert person.role.slug == Role.STAFF

    # Viewing the roles page needs no password; saving it does.
    assert client.get(reverse("accounts:roles")).status_code == 200
    response = client.post(reverse("accounts:roles"), {})
    assert "reauthenticate" in response["Location"]


def test_after_reauthentication_the_change_goes_through(client):
    boss, person = owner(), staff()
    sign_in(client, boss, recent_password=False)
    target = reverse("accounts:user_role", args=[person.pk])
    response = client.post(target, {"role": Role.objects.get(slug=Role.MANAGER).pk})
    response = client.post(response["Location"], {"password": "a-long-test-password"})
    person.refresh_from_db()
    assert person.role.slug == Role.MANAGER
