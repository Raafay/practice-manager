"""Every new address: signed out is sent to sign in, a portal user gets 403, the wrong role 403."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.aml import services as aml
from apps.aml.models import IdentityCheck, PolicyDocument, RiskQuestion, TrainingRecord
from apps.aml.tests.test_risk import submitted
from apps.clients.tests.factories import ClientFactory
from apps.onboarding import clearance, hmrc, letters
from apps.onboarding.models import ClearanceRequest
from apps.onboarding.tests.test_letters import onboarding_client_with_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    client_row, contact = onboarding_client_with_service()
    letter = letters.prepare_letter(manager(), client_row)
    aml.sync_checks(client_row)
    check = IdentityCheck.objects.filter(client=client_row).first()
    assessment = submitted(ClientFactory())
    auth = hmrc.add(manager(), client_row, tax="ct", method="post_code")
    req = clearance.start(
        manager(), client_row, accountant_name="Pat Previous", email="pat@example.com"
    )
    item = client_row.onboarding_items.first()
    return {
        "c": client_row,
        "letter": letter,
        "check": check,
        "assessment": assessment,
        "auth": auth,
        "req": req,
        "item": item,
        "question": RiskQuestion.objects.first(),
        "training": TrainingRecord.objects.create(
            person=manager(), trained_on="2026-01-01", course="Demo"
        ),
        "policy": PolicyDocument.objects.create(title="P", original_name="p.pdf"),
    }


def staff_addresses(w):
    c = w["c"].pk
    a = w["assessment"]
    return [
        ("onboarding:tab", [c], "get"),
        ("onboarding:item", [c, w["item"].pk], "get"),
        ("onboarding:item", [c, w["item"].pk], "post"),
        ("onboarding:make_live", [c], "get"),
        ("onboarding:make_live", [c], "post"),
        ("onboarding:engagement", [c], "get"),
        ("onboarding:prepare", [c], "post"),
        ("onboarding:letter", [c, w["letter"].pk], "get"),
        ("onboarding:letter", [c, w["letter"].pk], "post"),
        ("onboarding:letter_cancel", [c, w["letter"].pk], "post"),
        ("onboarding:letter_cancel_link", [c, w["letter"].pk], "post"),
        ("onboarding:hmrc", [c], "get"),
        ("onboarding:hmrc_add", [c], "get"),
        ("onboarding:hmrc_add", [c], "post"),
        ("onboarding:hmrc_edit", [c, w["auth"].pk], "get"),
        ("onboarding:hmrc_edit", [c, w["auth"].pk], "post"),
        ("onboarding:hmrc_reveal", [c, w["auth"].pk], "post"),
        ("onboarding:clearance_start", [c], "get"),
        ("onboarding:clearance_start", [c], "post"),
        ("onboarding:clearance_update", [c, w["req"].pk], "get"),
        ("onboarding:clearance_chase", [c, w["req"].pk], "post"),
        ("aml:tab", [c], "get"),
        ("aml:identity", [c, w["check"].pk], "get"),
        ("aml:identity", [c, w["check"].pk], "post"),
        ("aml:person_add", [c], "get"),
        ("aml:person_remove", [c, w["check"].pk], "get"),
        ("aml:start", [c], "post"),
        ("aml:assessment", [a.client_id, a.pk], "get"),
        ("aml:assessment", [a.client_id, a.pk], "post"),
        ("aml:approve", [a.client_id, a.pk], "post"),
        ("aml:send_back", [a.client_id, a.pk], "get"),
        ("aml:register", [], "get"),
        ("aml:register_export", [], "get"),
        ("aml:policy", [w["policy"].pk], "get"),
    ]


def settings_addresses(w):
    return [
        ("onboarding:checklist", [], "get"),
        ("onboarding:checklist_add", [], "get"),
        ("onboarding:letter_parts", [], "get"),
        ("onboarding:letter_part", ["terms"], "get"),
        ("aml:questions", [], "get"),
        ("aml:question_add", [], "get"),
        ("aml:question_edit", [w["question"].pk], "get"),
        ("aml:question_toggle", [w["question"].pk], "post"),
        ("aml:bands", [], "get"),
        ("aml:records", [], "get"),
        ("aml:training_add", [], "post"),
        ("aml:training_delete", [w["training"].pk], "post"),
        ("aml:policy_add", [], "post"),
        ("aml:policy_delete", [w["policy"].pk], "post"),
    ]


def call(client, name, args, method):
    return getattr(client, method)(reverse(name, args=args))


def test_every_address_sends_signed_out_users_to_sign_in(client, world):
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        response = call(client, name, args, method)
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_every_address_refuses_portal_users(client, world):
    sign_in(client, portal_user())
    for name, args, method in staff_addresses(world) + settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_settings_need_the_settings_right(client, world):
    sign_in(client, staff())
    for name, args, method in settings_addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_the_register_export_needs_the_export_right(client, world):
    sign_in(client, staff())
    assert call(client, "aml:register_export", [], "get").status_code == 403
    sign_in(client, owner())
    assert call(client, "aml:register_export", [], "get").status_code == 200


def test_an_object_under_the_wrong_client_is_not_found(client, world):
    sign_in(client, owner())
    other = ClientFactory()
    for name, args in [
        ("onboarding:item", [other.pk, world["item"].pk]),
        ("onboarding:letter", [other.pk, world["letter"].pk]),
        ("onboarding:hmrc_edit", [other.pk, world["auth"].pk]),
        ("onboarding:clearance_update", [other.pk, world["req"].pk]),
        ("aml:identity", [other.pk, world["check"].pk]),
        ("aml:assessment", [other.pk, world["assessment"].pk]),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 404, name
    assert ClearanceRequest.objects.count() == 1


def test_a_signing_link_opens_only_its_own_letter(client, world):
    """A link for one letter cannot be used to see or sign another client's letter."""
    from apps.onboarding.tests.test_letters import new_token, sent_letter

    c1, contact1, letter1 = sent_letter()
    c2, contact2, letter2 = sent_letter()
    link1, token1 = new_token(letter1)
    page = client.get(reverse("onboarding:sign", args=[token1]))
    assert page.status_code == 200
    body = page.content.decode()
    assert letter1.client.name in body
    # Nothing on the page names the other letter's client; no staff address opens signed out.
    assert reverse("onboarding:letter", args=[c2.pk, letter2.pk]) not in body
    assert client.get(reverse("onboarding:letter", args=[c2.pk, letter2.pk])).status_code == 302
    letter2.refresh_from_db()
    assert letter2.state == "sent"
