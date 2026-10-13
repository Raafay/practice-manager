import pytest
from django.urls import reverse

from apps import events
from apps.accounts.models import Role
from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.core.tests.encrypted_app.models import Secret
from apps.events.models import ActivityEvent, EventError, Notification
from apps.events.services import changes, snapshot

pytestmark = pytest.mark.django_db


def test_record_writes_one_event_with_actor_and_target():
    boss, person = owner(), staff()
    event = events.record(boss, "user.example", "Something happened.", target=person, colour="blue")
    assert event.actor == boss
    assert event.actor_label == str(boss)
    assert event.target == person
    assert event.target_label == str(person)
    assert event.data == {"colour": "blue"}


def test_record_without_actor_or_request_is_the_system():
    event = events.record(None, "system.example", "The system did something.")
    assert event.actor is None
    assert event.actor_label == "System"


def test_record_refuses_a_client_until_stage_two():
    with pytest.raises(ValueError):
        events.record(None, "client.changed", "x", client=object())


def test_events_are_never_changed_or_deleted():
    event = events.record(None, "system.example", "x")
    event.summary = "changed"
    with pytest.raises(EventError):
        event.save()
    with pytest.raises(EventError):
        event.delete()


def test_middleware_fills_in_the_user_and_address(client):
    person = staff()
    sign_in(client, person)
    client.post(
        reverse("events:notifications_read_all"),
        REMOTE_ADDR="198.51.100.7",
        HTTP_USER_AGENT="TestBrowser/1",
    )
    # A request-time record with actor=None picks up the signed-in user.
    from apps.events.context import RequestInfo, reset, set_current

    token = set_current(
        RequestInfo(user=person, ip_address="198.51.100.7", user_agent="TestBrowser/1")
    )
    try:
        event = events.record(None, "user.example", "x")
    finally:
        reset(token)
    assert event.actor == person
    assert event.ip_address == "198.51.100.7"
    assert event.user_agent == "TestBrowser/1"


def test_encrypted_values_never_reach_event_data():
    secret = Secret.objects.create(label="a", value="QQ000000A")
    before = snapshot(secret, ["label", "value"])
    secret.value = "QQ111111B"
    secret.label = "b"
    diff = changes(before, snapshot(secret, ["label", "value"]))
    assert "QQ" not in str(diff)
    assert diff["label"] == {"old": "a", "new": "b"}


def test_events_written_for_role_change_through_the_page(client):
    boss, person = owner(), staff()
    sign_in(client, boss)
    client.post(
        reverse("accounts:user_role", args=[person.pk]),
        {"role": Role.objects.get(slug="manager").pk},
    )
    event = ActivityEvent.objects.get(verb="user.role_changed")
    assert event.actor == boss
    assert event.ip_address == "127.0.0.1"


class TestAuditLog:
    def test_owner_only(self, client):
        sign_in(client, manager())
        assert client.get(reverse("events:audit_log")).status_code == 403
        client.logout()
        sign_in(client, staff())
        assert client.get(reverse("events:audit_log")).status_code == 403
        client.logout()
        assert client.get(reverse("events:audit_log")).status_code == 302

    def test_a_single_grant_opens_it(self, client):
        person = manager(extra_rights=["audit.view"])
        sign_in(client, person)
        assert client.get(reverse("events:audit_log")).status_code == 200

    def test_lists_and_filters(self, client):
        boss, person = owner(), staff()
        events.record(person, "user.example", "Person did a thing.")
        events.record(boss, "settings.changed", "Boss changed a setting.")
        sign_in(client, boss)
        page = client.get(reverse("events:audit_log"))
        assert b"Person did a thing." in page.content
        filtered = client.get(reverse("events:audit_log"), {"person": person.pk})
        assert b"Person did a thing." in filtered.content
        assert b"Boss changed a setting." not in filtered.content
        by_verb = client.get(reverse("events:audit_log"), {"verb": "settings.changed"})
        assert b"Boss changed a setting." in by_verb.content
        assert b"Person did a thing." not in by_verb.content


class TestNotifications:
    def test_notify_and_the_bell(self, client):
        person = staff()
        events.notify(person, "A task was given to you.", "/profile/")
        sign_in(client, person)
        page = client.get("/")
        assert b"Notifications, 1 unread" in page.content
        listing = client.get(reverse("events:notifications"))
        assert b"A task was given to you." in listing.content

    def test_opening_marks_read_and_follows_the_link(self, client):
        person = staff()
        note = events.notify(person, "Look at this.", "/profile/")
        sign_in(client, person)
        response = client.post(reverse("events:notification_open", args=[note.pk]))
        assert response["Location"] == "/profile/"
        note.refresh_from_db()
        assert note.read_at is not None

    def test_mark_all_read(self, client):
        person = staff()
        events.notify(person, "One")
        events.notify(person, "Two")
        sign_in(client, person)
        client.post(reverse("events:notifications_read_all"))
        assert not Notification.objects.unread_for(person).exists()

    def test_cannot_open_someone_elses(self, client):
        note = events.notify(staff(), "Private")
        sign_in(client, staff())
        assert client.post(reverse("events:notification_open", args=[note.pk])).status_code == 404

    @pytest.mark.parametrize(
        "link", ["https://example.com/", "//example.com/", "/\\example.com", "javascript:alert(1)"]
    )
    def test_links_must_stay_on_this_site(self, link):
        with pytest.raises(ValueError):
            events.notify(staff(), "x", link)
