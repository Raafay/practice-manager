import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.onboarding import services
from apps.onboarding.models import OnboardingItem
from apps.services.models import ClientService, Service

pytestmark = pytest.mark.django_db


def onboarding_client(**kwargs):
    client = ClientFactory(status="prospect", **kwargs)
    client_services.change_status(manager(), client, "onboarding")
    return client


def finish_needed(client):
    for item in client.onboarding_items.filter(needed_before_golive=True):
        services.set_item(manager(), item, "done")


def test_checklist_is_created_when_status_becomes_onboarding():
    client = onboarding_client()
    keys = list(client.onboarding_items.values_list("key", flat=True))
    assert len(keys) == 12 and keys[0] == "proposal_accepted"
    needed = set(
        client.onboarding_items.filter(needed_before_golive=True).values_list("key", flat=True)
    )
    assert needed == {
        "engagement_letter_signed",
        "client_details",
        "identity_verified",
        "risk_assessment_approved",
        "services_confirmed",
    }
    # Running it twice makes nothing new.
    assert services.ensure_checklist(client) == 0


def test_proposal_accepted_starts_onboarding_and_ticks_its_line():
    client = ClientFactory(status="prospect")
    services.on_proposal_accepted(client, actor=manager())
    client.refresh_from_db()
    assert client.status == "onboarding"
    assert client.onboarding_items.get(key="proposal_accepted").state == "done"


def test_gate_blocks_while_a_needed_item_is_open():
    client = onboarding_client()
    with pytest.raises(ValidationError, match="Not ready to go live"):
        services.make_live(manager(), client)
    client.refresh_from_db()
    assert client.status == "onboarding"


def test_gate_allows_when_all_needed_items_are_done_or_not_needed():
    client = onboarding_client()
    items = list(client.onboarding_items.filter(needed_before_golive=True))
    services.set_item(manager(), items[0], "not_needed")
    for item in items[1:]:
        services.set_item(manager(), item, "done")
    services.make_live(manager(), client)
    client.refresh_from_db()
    assert client.status == "active" and client.client_since is not None
    assert ActivityEvent.objects.filter(verb="onboarding.made_live", client=client).exists()


def test_override_needs_the_right_and_a_reason():
    client = onboarding_client()
    # Managers can change status but have no override right.
    with pytest.raises(ValidationError):
        services.make_live(manager(), client, override_reason="Urgent")
    boss = owner()
    with pytest.raises(ValidationError, match="reason"):
        services.make_live(boss, client)
    services.make_live(boss, client, override_reason="Client starts today.")
    client.refresh_from_db()
    assert client.status == "active"
    event = ActivityEvent.objects.get(verb="onboarding.override")
    assert "Client starts today." in event.summary


def test_staff_without_the_status_right_cannot_make_live():
    client = onboarding_client()
    finish_needed(client)
    with pytest.raises(PermissionDenied):
        services.make_live(staff(), client)


def test_making_live_activates_proposed_services_and_creates_deadlines(settings):
    client = onboarding_client(
        client_type="ltd",
        company_number="",
        incorporated_on=None,
    )
    service = (
        Service.objects.get(code="bookkeeping")
        if Service.objects.filter(code="bookkeeping").exists()
        else Service.objects.filter(applies_to__contains=["ltd"]).first()
    )
    from apps.services import services as svc

    svc.switch_on(manager(), client, service)
    cs = ClientService.objects.get(client=client)
    assert cs.state == "proposed"
    finish_needed(client)
    services.make_live(manager(), client)
    cs.refresh_from_db()
    assert cs.state == "active" and cs.starts_on is not None


def test_system_item_goes_back_to_todo_when_it_stops_holding():
    client = onboarding_client()
    services.sync_system_item(client, "identity_verified", True)
    item = client.onboarding_items.get(key="identity_verified")
    assert item.state == "done" and item.auto_ticked
    services.sync_system_item(client, "identity_verified", False)
    item.refresh_from_db()
    assert item.state == "todo"
    # A line ticked by hand stays put.
    services.set_item(manager(), item, "done")
    services.sync_system_item(client, "identity_verified", False)
    item.refresh_from_db()
    assert item.state == "done"


def test_status_form_cannot_make_a_client_live(client):
    target = onboarding_client()
    sign_in(client, manager())
    response = client.post(reverse("clients:status", args=[target.pk]), {"status": "active"})
    assert response.status_code == 422
    target.refresh_from_db()
    assert target.status == "onboarding"


# ---------------------------------------------------------------- pages


def test_pages_need_sign_in_and_the_right_role(client):
    target = onboarding_client()
    item = target.onboarding_items.first()
    urls = [
        reverse("onboarding:tab", args=[target.pk]),
        reverse("onboarding:item", args=[target.pk, item.pk]),
        reverse("onboarding:make_live", args=[target.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 302
    sign_in(client, staff())
    assert client.get(urls[0]).status_code == 200
    assert client.get(urls[2]).status_code == 403  # staff lack clients.status
    assert client.get(reverse("onboarding:checklist")).status_code == 403


def test_make_live_through_the_page(client):
    target = onboarding_client()
    finish_needed(target)
    sign_in(client, manager())
    page = client.get(reverse("onboarding:tab", args=[target.pk]))
    assert b"Make live" in page.content
    response = client.post(reverse("onboarding:make_live", args=[target.pk]))
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.status == "active"


def test_item_can_be_updated_by_hand(client):
    target = onboarding_client()
    item = target.onboarding_items.get(key="welcome_sent")
    sign_in(client, staff())
    response = client.post(
        reverse("onboarding:item", args=[target.pk, item.pk]),
        {"state": "done", "note": "Sent on the phone"},
    )
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.state == OnboardingItem.State.DONE and item.note == "Sent on the phone"


def test_checklist_template_is_edited_in_settings(client):
    sign_in(client, manager())
    assert client.get(reverse("onboarding:checklist")).status_code == 200
    response = client.post(
        reverse("onboarding:checklist_add"),
        {
            "name": "Sign the data sharing form",
            "needed_before_golive": "on",
            "position": 20,
            "active": "on",
        },
    )
    assert response.status_code == 302
    fresh = onboarding_client()
    assert fresh.onboarding_items.filter(name="Sign the data sharing form").exists()
