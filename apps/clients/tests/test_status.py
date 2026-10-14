from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients import services
from apps.clients.models import Client, CustomFieldDefinition, Document, Tag
from apps.core.models import PracticeSettings
from apps.events.models import ActivityEvent

from .factories import ClientContactFactory, ClientFactory, DocumentFactory, NoteFactory

pytestmark = pytest.mark.django_db


def change(client, target, status, **extra):
    return client.post(reverse("clients:status", args=[target.pk]), {"status": status, **extra})


def test_status_moves_follow_the_rules(client):
    target = ClientFactory(status="prospect")
    sign_in(client, manager())
    assert change(client, target, "active").status_code == 422  # prospects go to onboarding first
    assert change(client, target, "onboarding").status_code == 302
    target.refresh_from_db()
    assert target.status == "onboarding"
    # The onboarding gate (Stage 7): no way to go live by hand from the status form.
    assert change(client, target, "active").status_code == 422
    target.refresh_from_db()
    assert target.status == "onboarding"
    services.set_status(manager(), target, "active")
    target.refresh_from_db()
    assert target.status == "active" and target.client_since is not None
    assert change(client, target, "lost").status_code == 422
    assert change(client, target, "paused").status_code == 302
    event = ActivityEvent.objects.filter(verb="client.status_changed").first()
    assert event.client == target and "Active to Paused" in event.summary


def test_every_status_has_the_documented_moves():
    assert services.STATUS_MOVES == {
        "prospect": ("onboarding", "lost"),
        "onboarding": ("active", "paused", "former"),
        "active": ("paused", "former"),
        "paused": ("active", "former"),
        "former": ("active",),
        "lost": ("prospect",),
    }


def test_becoming_former_sets_the_end_date_and_retention_dates(client):
    target = ClientFactory(status="active")
    practice = PracticeSettings.load()
    assert (practice.retention_years, practice.aml_retention_years) == (6, 5)
    sign_in(client, owner())
    change(client, target, "former", ended_on="2026-03-31")
    target.refresh_from_db()
    assert target.relationship_ended_on == date(2026, 3, 31)
    assert target.retain_until == date(2032, 3, 31)
    assert target.aml_retain_until == date(2031, 3, 31)
    # Coming back clears them.
    change(client, target, "active")
    target.refresh_from_db()
    assert target.relationship_ended_on is None and target.retain_until is None


def test_retention_years_are_settings():
    practice = PracticeSettings.load()
    practice.retention_years, practice.aml_retention_years = 7, 10
    practice.save()
    target = ClientFactory(status="active")
    services.change_status(owner(), target, "former", ended_on=date(2026, 1, 31))
    assert target.retain_until == date(2033, 1, 31) and target.aml_retain_until == date(2036, 1, 31)


def test_changing_status_needs_the_right(client):
    target = ClientFactory()
    sign_in(client, staff())
    assert client.get(reverse("clients:status", args=[target.pk])).status_code == 403
    assert change(client, target, "paused").status_code == 403
    target.refresh_from_db()
    assert target.status == "active"
    with pytest.raises(Exception):  # noqa: B017 - the service checks the right too
        services.change_status(staff(), target, "paused")


def test_archive_needs_a_reason_and_the_right(client):
    target = ClientFactory(name="Archive Me Ltd")
    sign_in(client, staff())
    assert (
        client.post(reverse("clients:archive", args=[target.pk]), {"reason": "x"}).status_code
        == 403
    )
    sign_in(client, manager())
    assert (
        client.post(reverse("clients:archive", args=[target.pk]), {"reason": ""}).status_code == 422
    )
    assert (
        client.post(reverse("clients:archive", args=[target.pk]), {"reason": "   "}).status_code
        == 422
    )
    target.refresh_from_db()
    assert not target.is_archived
    response = client.post(reverse("clients:archive", args=[target.pk]), {"reason": "Moved abroad"})
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_archived and target.archive_reason == "Moved abroad"
    event = ActivityEvent.objects.get(verb="client.archived")
    assert "Moved abroad" in event.summary and event.client == target
    # Hidden from list and search, still reachable, and can be restored.
    assert "Archive Me Ltd" not in [
        c.name for c in client.get(reverse("clients:list")).context["page"]
    ]
    assert not services.search_clients("archive").exists()
    assert b"Archived on" in client.get(reverse("clients:detail", args=[target.pk])).content
    client.post(reverse("clients:restore", args=[target.pk]))
    target.refresh_from_db()
    assert not target.is_archived
    assert ActivityEvent.objects.filter(verb="client.restored").exists()


def test_delete_needs_the_right_and_the_typed_name(client):
    target = ClientFactory(name="Delete Me Ltd")
    sign_in(client, manager())
    assert client.get(reverse("clients:delete", args=[target.pk])).status_code == 403
    assert (
        client.post(
            reverse("clients:delete", args=[target.pk]), {"confirm_name": target.name}
        ).status_code
        == 403
    )
    sign_in(client, owner())
    wrong = client.post(
        reverse("clients:delete", args=[target.pk]), {"confirm_name": "delete me ltd"}
    )
    assert wrong.status_code == 422 and Client.objects.filter(pk=target.pk).exists()
    ok = client.post(reverse("clients:delete", args=[target.pk]), {"confirm_name": "Delete Me Ltd"})
    assert ok.status_code == 302 and not Client.objects.filter(pk=target.pk).exists()


def test_delete_is_blocked_while_retention_runs(client):
    target = ClientFactory(
        name="Kept Ltd",
        status="former",
        retain_until=date(2099, 1, 1),
        aml_retain_until=date(2020, 1, 1),
    )
    sign_in(client, owner())
    response = client.post(
        reverse("clients:delete", args=[target.pk]), {"confirm_name": "Kept Ltd"}
    )
    assert response.status_code == 422
    assert b"must be kept until 01/01/2099" in response.content
    assert Client.objects.filter(pk=target.pk).exists()
    # The AML date alone also blocks.
    target.retain_until, target.aml_retain_until = date(2020, 1, 1), date(2099, 6, 1)
    target.save()
    assert (
        client.post(
            reverse("clients:delete", args=[target.pk]), {"confirm_name": "Kept Ltd"}
        ).status_code
        == 422
    )
    # Once both have passed it goes.
    target.aml_retain_until = date(2020, 6, 1)
    target.save()
    assert (
        client.post(
            reverse("clients:delete", args=[target.pk]), {"confirm_name": "Kept Ltd"}
        ).status_code
        == 302
    )


def test_delete_for_good_keeps_a_labelled_event_and_removes_files_and_links(client):
    target = ClientFactory(name="Gone Ltd")
    link = ClientContactFactory(client=target)
    NoteFactory(client=target)
    doc = DocumentFactory(client=target)
    stored, storage = doc.file.name, doc.file.storage
    from apps import events

    events.record(None, "client.changed", "Earlier change.", client=target)
    sign_in(client, owner())
    client.post(reverse("clients:delete", args=[target.pk]), {"confirm_name": "Gone Ltd"})
    assert not Document.objects.exists() and not storage.exists(stored)
    from apps.clients.models import Contact

    assert Contact.objects.filter(pk=link.contact.pk).exists()
    earlier = ActivityEvent.objects.get(summary="Earlier change.")
    assert earlier.client is None and earlier.client_label.startswith("Gone Ltd")
    deleted = ActivityEvent.objects.get(verb="client.deleted")
    assert "Gone Ltd" in deleted.summary and deleted.client_label.startswith("Gone Ltd")


def test_settings_tags_and_custom_fields_need_the_settings_right(client):
    sign_in(client, staff())
    assert (
        client.post(reverse("clients:tag_add"), {"name": "VIP", "colour": "#112233"}).status_code
        == 403
    )
    sign_in(client, manager())
    assert (
        client.post(reverse("clients:tag_add"), {"name": "VIP", "colour": "#112233"}).status_code
        == 302
    )
    tag = Tag.objects.get()
    assert (
        client.post(reverse("clients:tag_add"), {"name": "Bad", "colour": "red"}).status_code == 422
    )
    client.post(
        reverse("clients:tag_edit", args=[tag.pk]), {"name": "Very important", "colour": "#445566"}
    )
    tag.refresh_from_db()
    assert tag.name == "Very important"
    duplicate = client.post(
        reverse("clients:tag_add"), {"name": "very IMPORTANT", "colour": "#112233"}
    )
    assert duplicate.status_code == 422
    client.post(
        reverse("clients:custom_field_add"), {"name": "Software", "kind": "text", "position": 1}
    )
    field = CustomFieldDefinition.objects.get()
    assert b"Software" in client.get(reverse("clients:custom_fields")).content
    client.post(reverse("clients:custom_field_delete", args=[field.pk]))
    client.post(reverse("clients:tag_delete", args=[tag.pk]))
    assert not CustomFieldDefinition.objects.exists() and not Tag.objects.exists()
    assert ActivityEvent.objects.filter(verb="setting.changed").count() >= 5


def test_deactivating_a_person_hands_over_their_clients(client):
    boss = owner()
    leaver, successor = staff(), staff()
    mine = ClientFactory(manager=leaver, partner=boss)
    both = ClientFactory(manager=leaver, partner=leaver)
    ClientFactory(manager=leaver, status="former")  # not live: left alone
    sign_in(client, boss)
    url = reverse("accounts:user_deactivate", args=[leaver.pk])
    detail = client.get(reverse("accounts:user_detail", args=[leaver.pk]))
    assert detail.context["open_clients"] == 2
    client.post(url)  # no successor chosen
    leaver.refresh_from_db()
    assert leaver.is_active
    client.post(url, {"hand_over_to": leaver.pk})  # cannot hand to themselves
    leaver.refresh_from_db()
    assert leaver.is_active
    client.post(url, {"hand_over_to": successor.pk})
    leaver.refresh_from_db()
    assert not leaver.is_active
    mine.refresh_from_db()
    both.refresh_from_db()
    assert mine.manager == successor and mine.partner == boss
    assert both.manager == successor and both.partner == successor
    assert ActivityEvent.objects.filter(verb="client.handed_over").count() == 2
    assert User.objects.get(pk=successor.pk).is_active


def test_deactivating_someone_with_no_clients_needs_no_successor(client):
    boss, leaver = owner(), staff()
    sign_in(client, boss)
    client.post(reverse("accounts:user_deactivate", args=[leaver.pk]))
    leaver.refresh_from_db()
    assert not leaver.is_active


def test_service_refuses_a_bad_status_directly():
    target = ClientFactory(status="lost")
    with pytest.raises(ValidationError):
        services.change_status(owner(), target, "active")
