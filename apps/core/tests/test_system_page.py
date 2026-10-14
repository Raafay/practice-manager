"""Settings, System for the owner (Stage 13, item 9)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, sign_in
from apps.core.models import PracticeSettings

pytestmark = pytest.mark.django_db


def test_the_system_page_is_for_the_owner(client):
    sign_in(client, manager())
    assert client.get(reverse("core:system")).status_code == 403
    sign_in(client, owner())
    page = client.get(reverse("core:system")).content.decode()
    for heading in ("Version", "Backups", "Background jobs", "Email", "Companies House and Xero"):
        assert heading in page
    assert "Worker not running" in page
    assert "Pause all automatic sending" in page


def test_the_worker_shows_as_running_after_a_heartbeat(client):
    from apps.jobs import services

    services.heartbeat(timezone.now())
    sign_in(client, owner())
    assert "Worker running" in client.get(reverse("core:system")).content.decode()


def test_the_backup_note_is_saved_and_logged(client):
    from apps.events.models import ActivityEvent

    boss = owner(name="Morgan Sample")
    sign_in(client, boss)
    client.post(reverse("core:system_backup"), {"backup_note": "Restore test done."})
    practice = PracticeSettings.load()
    assert practice.backup_note == "Restore test done."
    assert practice.backup_note_on == timezone.localdate()
    assert practice.backup_note_by == "Morgan Sample"
    assert ActivityEvent.objects.filter(verb="setting.changed", actor=boss).exists()
    assert "Restore test done." in client.get(reverse("core:system")).content.decode()


def test_pausing_from_the_system_page_comes_back_to_it(client):
    sign_in(client, owner())
    response = client.post(reverse("comms:pause"), {"paused": "1", "next": reverse("core:system")})
    assert response["Location"] == reverse("core:system")
    assert PracticeSettings.load().comms_paused is True
