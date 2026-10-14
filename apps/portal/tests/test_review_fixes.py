"""Portal fixes from the Stage 13 security review (docs/SECURITY-REVIEW.md)."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import manager
from apps.clients.tests.factories import ClientFactory, DocumentFactory
from apps.portal import services
from apps.portal.models import PortalItem
from apps.portal.tests.helpers import portal_login, portal_person

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_directors():
    boss = manager()
    cl = ClientFactory(name="Alpha Ltd", manager=boss)
    user_a, contact_a, _ = portal_person(cl, first_name="Avery", last_name="Able")
    user_b, contact_b, _ = portal_person(cl, first_name="Blake", last_name="Baker", main=False)
    item = services.create_item(
        boss, cl, PortalItem.Kind.CLIENT_DETAILS, "Your details", reuse=False
    )
    return {"cl": cl, "a": (user_a, contact_a), "b": (user_b, contact_b), "item": item}


def test_a_draft_answer_is_not_shown_to_a_colleague(two_directors):
    from apps.portal.formspecs import person_key

    user_a, contact_a = two_directors["a"]
    user_b, _ = two_directors["b"]
    url = reverse("portal:form", args=[two_directors["item"].public_id])
    secret_home = "12 MADE-UP-HOME-MARKER Road"
    a = portal_login(Client(), user_a)
    a.post(url, {person_key(contact_a, "home_address"): secret_home, "save": "1"})
    b = portal_login(Client(), user_b)
    page = b.get(url).content.decode()
    assert "MADE-UP-HOME-MARKER" not in page
    # B saving the form does not wipe what A typed.
    b.post(url, {"trading_name": "Alpha", "save": "1"})
    from apps.portal.models import PortalForm

    form = PortalForm.objects.get(item=two_directors["item"])
    assert form.answers[person_key(contact_a, "home_address")] == secret_home
    # A still sees their own answer.
    assert "MADE-UP-HOME-MARKER" in a.get(url).content.decode()


def test_a_sensitive_upload_is_seen_only_by_the_person_who_sent_it(two_directors):
    user_a, _ = two_directors["a"]
    user_b, _ = two_directors["b"]
    passport = DocumentFactory(
        client=two_directors["cl"],
        title="PASSPORT-MARKER",
        source="portal",
        sensitive=True,
        uploaded_by=user_a,
    )
    url = reverse("portal:document", args=[passport.public_id])
    b = portal_login(Client(), user_b)
    assert b.get(url).status_code == 404
    assert "PASSPORT-MARKER" not in b.get(reverse("portal:documents")).content.decode()
    a = portal_login(Client(), user_a)
    assert a.get(url).status_code == 200
