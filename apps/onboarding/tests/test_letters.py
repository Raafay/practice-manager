import hashlib
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, sign_in, staff
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.comms.models import QueuedMessage
from apps.core import actionlinks
from apps.core.models import ActionLink
from apps.events.models import ActivityEvent
from apps.onboarding import letters, services
from apps.onboarding.models import EngagementLetter, LetterPart
from apps.services import services as svc
from apps.services.models import Service

pytestmark = pytest.mark.django_db


def onboarding_client_with_service():
    client = ClientFactory(status="prospect", name="Sample Trading Ltd")
    contact = ContactFactory(first_name="Sam", last_name="Sample", email="sam@example.com")
    ClientContactFactory(client=client, contact=contact, is_main=True, can_sign=True)
    client_services.change_status(manager(), client, "onboarding")
    service = Service.objects.filter(code="accounts").first() or Service.objects.first()
    svc.switch_on(manager(), client, service, fee_amount=100)
    return client, contact


def sent_letter():
    client, contact = onboarding_client_with_service()
    boss = manager()
    letter = letters.prepare_letter(boss, client)
    letters.send_letter(boss, letter)
    letter.refresh_from_db()
    return client, contact, letter


def new_token(letter):
    ActionLink.objects.filter(object_id=letter.pk).delete()
    link, token = actionlinks.create(
        purpose="sign_letter", contact=letter.signer, client=letter.client, object_id=letter.pk
    )
    return link, token


def test_prepare_builds_the_letter_from_the_parts_and_services():
    client, contact = onboarding_client_with_service()
    letter = letters.prepare_letter(manager(), client)
    assert letter.state == "draft" and letter.version == 1
    assert "Dear Sam" in letter.body_html
    assert "Schedule 1" in letter.body_html and "Standard terms" in letter.body_html
    assert "Privacy notice" in letter.body_html
    assert letter.services and letter.services[0]["fee"] == "100.00"
    assert letter.signer == contact
    assert letters.uses_starter_wording()


def test_cannot_prepare_without_someone_to_sign():
    client = ClientFactory(status="onboarding")
    with pytest.raises(ValidationError, match="email address"):
        letters.prepare_letter(manager(), client)


def test_sending_freezes_makes_pdf_and_queues_the_email():
    client, contact, letter = sent_letter()
    assert letter.state == "sent" and letter.unsigned_document is not None
    pdf_bytes = letter.unsigned_document.file.read()
    assert pdf_bytes.startswith(b"%PDF")
    assert letter.fingerprint == hashlib.sha256(pdf_bytes).hexdigest()
    message = QueuedMessage.objects.get(client=client)
    assert message.state == "needs_approval" and message.to == "sam@example.com"
    assert "/sign/" in message.body_html
    # Only the hash of the token is stored.
    link = ActionLink.objects.get(object_id=letter.pk)
    token = message.body_html.split("/sign/")[1].split("/")[0]
    assert link.token_hash == actionlinks.hash_token(token) and token not in link.token_hash


def test_a_sent_letter_is_not_editable_or_sendable_twice():
    client, contact, letter = sent_letter()
    with pytest.raises(ValidationError):
        letters.send_letter(manager(), letter)
    with pytest.raises(ValidationError):
        letters.save_draft(manager(), letter, body_html="<p>x</p>", signer=contact)


def test_signing_makes_a_signed_pdf_whose_fingerprint_matches():
    client, contact, letter = sent_letter()
    link, token = new_token(letter)
    done = letters.sign_letter(
        link, typed_name="Sam Sample", agreed=True, ip="203.0.113.7", agent="TestBrowser/1"
    )
    assert done.state == "signed" and done.typed_name == "Sam Sample"
    assert done.ip_address == "203.0.113.7" and done.review_due is not None
    signed = done.signed_document.file.read()
    assert signed.startswith(b"%PDF") and signed != letter.unsigned_document.file.read()
    unsigned = done.unsigned_document.file.read()
    assert hashlib.sha256(unsigned).hexdigest() == done.fingerprint
    assert done.signed_document.category == "engagement"
    # The checklist line and the copy for the client.
    assert client.onboarding_items.get(key="engagement_letter_signed").state == "done"
    assert QueuedMessage.objects.filter(client=client, reason__startswith="Signed copy").exists()
    assert ActivityEvent.objects.filter(verb="letter.signed", client=client).exists()


def test_the_final_page_states_who_signed_and_the_fingerprint():
    client, contact, letter = sent_letter()
    page = letters._signature_page(
        letter, "Sam Sample", "sam@example.com", timezone.now(), "203.0.113.7", "Agent"
    )
    for text in ("Sam Sample", "sam@example.com", "203.0.113.7", letter.fingerprint, "UTC"):
        assert text in page


def test_a_link_cannot_sign_twice():
    client, contact, letter = sent_letter()
    link, token = new_token(letter)
    letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip=None, agent="")
    with pytest.raises(ValidationError, match="already been signed"):
        letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip=None, agent="")


def test_signing_needs_the_tick_and_a_name():
    client, contact, letter = sent_letter()
    link, token = new_token(letter)
    with pytest.raises(ValidationError):
        letters.sign_letter(link, typed_name="Sam Sample", agreed=False, ip=None, agent="")
    with pytest.raises(ValidationError):
        letters.sign_letter(link, typed_name=" ", agreed=True, ip=None, agent="")
    letter.refresh_from_db()
    assert letter.state in ("sent", "viewed")


def test_signing_a_new_letter_replaces_the_old_one():
    client, contact, letter = sent_letter()
    link, token = new_token(letter)
    letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip=None, agent="")
    second = letters.prepare_letter(manager(), client)
    letters.send_letter(manager(), second)
    link2, _ = new_token(second)
    letters.sign_letter(link2, typed_name="Sam Sample", agreed=True, ip=None, agent="")
    letter.refresh_from_db()
    assert letter.state == "replaced" and second.version == 2


# ---------------------------------------------------------------- the public page


def test_signing_page_works_without_signing_in_and_marks_viewed(client):
    c, contact, letter = sent_letter()
    link, token = new_token(letter)
    page = client.get(reverse("onboarding:sign", args=[token]))
    assert page.status_code == 200 and b"Sample Trading Ltd" in page.content
    assert page["X-Robots-Tag"].startswith("noindex")
    letter.refresh_from_db()
    assert letter.state == "viewed"
    # The page can be opened many times.
    assert client.get(reverse("onboarding:sign", args=[token])).status_code == 200
    pdf = client.get(reverse("onboarding:sign_pdf", args=[token]))
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf["X-Content-Type-Options"] == "nosniff"


def test_signing_through_the_page_and_second_post_refused(client):
    c, contact, letter = sent_letter()
    link, token = new_token(letter)
    url = reverse("onboarding:sign", args=[token])
    response = client.post(url, {"agree": "on", "typed_name": "Sam Sample"})
    assert response.status_code == 200 and b"was signed by Sam Sample" in response.content
    again = client.post(url, {"agree": "on", "typed_name": "Sam Sample"})
    assert again.status_code == 422 and b"already been signed" in again.content


def test_bad_expired_and_cancelled_links_are_not_found(client):
    c, contact, letter = sent_letter()
    assert client.get(reverse("onboarding:sign", args=["not-a-real-token"])).status_code == 404
    link, token = new_token(letter)
    link.expires_at = timezone.now() - timedelta(seconds=1)
    link.save()
    assert client.get(reverse("onboarding:sign", args=[token])).status_code == 404
    link2, token2 = new_token(letter)
    letters.cancel_signing_link(manager(), letter)
    assert client.get(reverse("onboarding:sign", args=[token2])).status_code == 404
    assert client.post(reverse("onboarding:sign", args=[token2]), {}).status_code == 404


def test_a_link_for_one_purpose_does_not_open_another_letter(client):
    c, contact, letter = sent_letter()
    link, token = actionlinks.create(
        purpose="proposal", contact=contact, client=c, object_id=letter.pk
    )
    assert client.get(reverse("onboarding:sign", args=[token])).status_code == 404


def test_signing_page_is_rate_limited(client):
    c, contact, letter = sent_letter()
    link, token = new_token(letter)
    url = reverse("onboarding:sign", args=[token])
    for _ in range(10):
        client.post(url, {})
    assert client.post(url, {}).status_code == 429


def test_a_draft_or_cancelled_letter_cannot_be_reached_by_a_link(client):
    c, contact = onboarding_client_with_service()
    letter = letters.prepare_letter(manager(), c)
    link, token = actionlinks.create(
        purpose="sign_letter", contact=contact, client=c, object_id=letter.pk
    )
    assert client.get(reverse("onboarding:sign", args=[token])).status_code == 404


# ---------------------------------------------------------------- staff pages


def test_engagement_pages_need_sign_in(client):
    c, contact, letter = sent_letter()
    for name, args in [
        ("onboarding:engagement", [c.pk]),
        ("onboarding:letter", [c.pk, letter.pk]),
        ("onboarding:letter_parts", []),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 302
    assert client.post(reverse("onboarding:prepare", args=[c.pk])).status_code == 302


def test_staff_can_prepare_edit_and_send_from_the_pages(client):
    c, contact = onboarding_client_with_service()
    sign_in(client, staff())
    response = client.post(reverse("onboarding:prepare", args=[c.pk]))
    assert response.status_code == 302
    letter = EngagementLetter.objects.get(client=c)
    page = client.get(reverse("onboarding:letter", args=[c.pk, letter.pk]))
    assert page.status_code == 200 and b"Starter text" in page.content
    response = client.post(
        reverse("onboarding:letter", args=[c.pk, letter.pk]),
        {"signer": contact.pk, "body_html": "<p>Hello {{ contact.first_name }}</p>", "send": "1"},
    )
    assert response.status_code == 302
    letter.refresh_from_db()
    assert letter.state == "sent"
    assert client.get(reverse("onboarding:engagement", args=[c.pk])).status_code == 200


def test_unknown_merge_field_blocks_sending(client):
    c, contact = onboarding_client_with_service()
    letter = letters.prepare_letter(manager(), c)
    letter.body_html = "<p>{{ nonsense }}</p>"
    letter.save()
    with pytest.raises(ValidationError, match="Unknown merge field"):
        letters.send_letter(manager(), letter)


def test_letter_wording_is_edited_in_settings_and_loses_the_starter_flag(client):
    sign_in(client, manager())
    url = reverse("onboarding:letter_part", args=["terms"])
    assert client.get(url).status_code == 200
    assert client.post(url, {"body": "<p>Our own terms.</p><script>x</script>"}).status_code == 302
    part = LetterPart.objects.get(key="terms")
    assert part.starter is False and "<script>" not in part.body
    sign_in(client, staff())
    assert client.get(reverse("onboarding:letter_parts")).status_code == 403


def test_services_changed_offers_a_new_letter():
    client, contact, letter = sent_letter()
    link, token = new_token(letter)
    letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip=None, agent="")
    assert not letters.services_changed_since_signed(client)
    other = (
        Service.objects.exclude(code=letter.services[0]["code"])
        .filter(applies_to__contains=["ltd"])
        .first()
    )
    svc.switch_on(manager(), client, other)
    assert letters.services_changed_since_signed(client)
    assert services.gate_problems(client) is not None
