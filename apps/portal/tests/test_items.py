"""Things to do: uploads, "That is everything", approving a document, letters and proposals."""

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.tests.factories import manager, staff
from apps.clients.models import Document
from apps.clients.tests.factories import ClientFactory, DocumentFactory
from apps.comms import merge
from apps.core import actionlinks
from apps.events.models import ActivityEvent, Notification
from apps.onboarding import letters
from apps.onboarding.tests.test_letters import sent_letter
from apps.pipeline.tests.test_proposals import sent_proposal
from apps.portal import services
from apps.portal.models import PortalItem
from apps.portal.tests.helpers import pdf_upload, portal_login, portal_person
from apps.tasks.models import TaskDocument
from apps.tasks.tests.factories import make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(client):
    boss = manager()
    cl = ClientFactory(name="Alpha Ltd", manager=boss)
    user, contact, link = portal_person(cl)
    portal_login(client, user)
    return {"boss": boss, "cl": cl, "user": user, "contact": contact, "http": client}


def upload_item(w, owner=None):
    task = make_task(w["boss"], client=w["cl"], owner=owner or w["boss"])
    task.steps.create(name="Records received", stops_reminders=True, position=1)
    item = services.create_item(
        w["boss"], w["cl"], PortalItem.Kind.UPLOAD_RECORDS, "Upload your records", task=task
    )
    return task, item


# ---------------------------------------------------------------- uploads


def test_an_upload_becomes_a_portal_document_and_tells_the_manager(setup):
    http, cl = setup["http"], setup["cl"]
    response = http.post(
        reverse("portal:upload"),
        {"category": "bookkeeping", "note": "March statements", "files": [pdf_upload("a.pdf")]},
    )
    assert response.status_code == 302
    doc = Document.objects.get(client=cl)
    assert doc.source == Document.Source.PORTAL and doc.uploaded_by == setup["user"]
    assert doc.contact == setup["contact"] and doc.category == "bookkeeping"
    assert "March statements" in doc.title and not doc.shared_with_portal
    assert Notification.objects.filter(user=setup["boss"], message__contains="uploaded").exists()
    assert ActivityEvent.objects.filter(verb="document.uploaded", client=cl).exists()
    # The person sees their own upload, not anyone else's staff-only files.
    DocumentFactory(client=cl, title="Staff only")
    page = http.get(reverse("portal:documents")).content.decode()
    assert "March statements" in page and "Staff only" not in page


def test_identity_uploads_are_sensitive_and_their_download_is_logged(setup):
    http = setup["http"]
    http.post(
        reverse("portal:upload"),
        {"category": "identity", "files": [pdf_upload("passport.pdf")]},
    )
    doc = Document.objects.get(client=setup["cl"])
    assert doc.sensitive
    response = http.get(reverse("portal:document", args=[doc.public_id]))
    assert response.status_code == 200 and response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert ActivityEvent.objects.filter(verb="document.downloaded", target_id=str(doc.pk)).exists()


def test_portal_upload_file_rules(setup):
    http = setup["http"]
    from django.core.files.uploadedfile import SimpleUploadedFile

    bad_type = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
    fake_pdf = SimpleUploadedFile("fake.pdf", b"not a pdf", content_type="application/pdf")
    for bad in (bad_type, fake_pdf):
        response = http.post(reverse("portal:upload"), {"category": "other", "files": [bad]})
        assert response.status_code == 422
    response = http.post(reverse("portal:upload"), {"category": "other"})
    assert response.status_code == 422
    assert not Document.objects.exists()


# ---------------------------------------------------------------- "That is everything"


def test_that_is_everything_ticks_the_stop_step_once_and_tells_the_owner(setup):
    owner = staff()
    task, item = upload_item(setup, owner=owner)
    step = task.steps.get()
    url = reverse("portal:item_everything", args=[item.public_id])
    assert setup["http"].post(url).status_code == 302
    step.refresh_from_db()
    item.refresh_from_db()
    assert step.done_at is not None and item.state == "done"
    ticks = ActivityEvent.objects.filter(verb="task.step_done", target_id=str(task.pk)).count()
    told = Notification.objects.filter(user=owner, message__contains="uploaded everything").count()
    assert (ticks, told) == (1, 1)
    # Pressing it again does nothing more.
    setup["http"].post(url)
    assert ActivityEvent.objects.filter(verb="task.step_done").count() == ticks
    assert (
        Notification.objects.filter(user=owner, message__contains="uploaded everything").count()
        == 1
    )


def test_an_upload_against_an_item_attaches_to_its_task(setup):
    task, item = upload_item(setup)
    url = reverse("portal:item_upload", args=[item.public_id])
    setup["http"].post(url, {"category": "vat", "files": [pdf_upload()]})
    assert TaskDocument.objects.filter(task=task).count() == 1
    assert Document.objects.filter(client=setup["cl"], source="portal").count() == 1


def test_the_item_page_for_uploading_shows_the_everything_button(setup):
    _, item = upload_item(setup)
    page = setup["http"].get(reverse("portal:item", args=[item.public_id])).content.decode()
    assert "That is everything" in page


# ---------------------------------------------------------------- approve a document


def test_approving_a_document_records_it_and_ticks_the_step(setup):
    boss, cl = setup["boss"], setup["cl"]
    doc = DocumentFactory(client=cl, title="Draft accounts")
    task = make_task(boss, client=cl, owner=boss)
    task.steps.create(name="Client approved", position=1)
    item = services.create_item(
        boss, cl, PortalItem.Kind.APPROVE_DOCUMENT, "Approve the accounts",
        object_id=doc.pk, task=task,
    )  # fmt: skip
    url = reverse("portal:item_approve", args=[item.public_id])
    http = setup["http"]
    response = http.post(url, {"typed_name": "Sam Sample"})  # no tick
    assert response.status_code == 422
    response = http.post(url, {"typed_name": "Sam Sample", "agree": "on"})
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.state == "done" and task.steps.get().done_at is not None
    page = Document.objects.get(title__startswith="Approval of")
    assert page.client == cl and page.content_type == "application/pdf"
    event = ActivityEvent.objects.get(verb="portal.document_approved")
    assert event.data["fingerprint"] and event.ip_address is not None
    # It can only be done once.
    assert http.post(url, {"typed_name": "Sam Sample", "agree": "on"}).status_code == 422


# ---------------------------------------------------------------- letters and proposals


def test_a_sent_letter_appears_as_a_thing_to_do_and_leads_to_the_signing_page(client):
    cl, contact, letter = sent_letter()
    # Give the signer portal access.
    signer = letter.signer
    from apps.accounts.models import User
    from apps.clients.models import ClientContact

    signer_user = User.objects.create_user(
        signer.email, name=signer.full_name, kind="portal", role=None
    )
    signer.portal_user = signer_user
    signer.save()
    ClientContact.objects.filter(client=cl, contact=signer).update(portal_access=True)
    letter.save()  # the app saves a letter whenever its state moves; the item follows
    del contact
    client.force_login(signer_user)
    item = PortalItem.objects.get(client=cl, kind="sign_letter", object_id=letter.pk)
    assert "Read and sign" in client.get(reverse("portal:home")).content.decode()
    response = client.get(reverse("portal:item", args=[item.public_id]))
    assert response.status_code == 302 and response.url.startswith("/sign/")
    token = response.url.split("/")[2]
    link = actionlinks.resolve(token, "sign_letter")
    assert link is not None and link.contact == signer and link.object_id == letter.pk
    # The short-lived link is the same signing mechanism; signing closes the item.
    letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip="127.0.0.1", agent="test")
    item.refresh_from_db()
    assert item.state == "done"


def test_a_colleague_who_cannot_sign_is_not_sent_to_the_signing_page(client):
    cl, _, letter = sent_letter()
    user, _, _ = portal_person(cl, main=False, can_sign=False)
    item = services.create_item(None, cl, PortalItem.Kind.SIGN_LETTER, "Sign", object_id=letter.pk)
    client.force_login(user)
    response = client.get(reverse("portal:item", args=[item.public_id]))
    assert response.status_code == 200
    assert "ask the person named on the letter" in response.content.decode()


def test_a_sent_proposal_appears_and_a_decision_closes_it(client):
    cl, proposal, _ = sent_proposal()
    contact = proposal.contact
    from apps.accounts.models import User
    from apps.clients.models import ClientContact

    user = User.objects.create_user(
        "pat-portal@example.com", name=contact.full_name, kind="portal", role=None
    )
    contact.portal_user = user
    contact.save()
    ClientContact.objects.update_or_create(
        client=cl, contact=contact, defaults={"portal_access": True}
    )
    proposal.save()
    item = PortalItem.objects.get(client=cl, kind="accept_proposal", object_id=proposal.pk)
    client.force_login(user)
    response = client.get(reverse("portal:item", args=[item.public_id]))
    assert response.status_code == 302 and response.url.startswith("/proposal/")
    proposal.state = "declined"
    proposal.save()
    item.refresh_from_db()
    assert item.state == "done"


# ---------------------------------------------------------------- link fields in emails


def test_upload_and_portal_links_work_in_templates_and_make_one_item(setup):
    cl = setup["cl"]
    task = make_task(setup["boss"], client=cl)
    ctx = merge.Context(client=cl, contact=setup["contact"], user=setup["boss"], task=task)
    first = merge.render("<p>{{ upload_link }} {{ portal_link }} {{ request_link }}</p>", ctx)
    assert not first.blocked, first.problems()
    assert "/portal/items/" in first.html and "/portal/" in first.html and "/r/" in first.html
    merge.render("<p>{{ upload_link }}</p>", ctx)
    assert PortalItem.objects.filter(client=cl, kind="upload_records", task=task).count() == 1


def test_the_confirm_link_works_in_a_template(setup):
    ctx = merge.Context(client=setup["cl"], contact=setup["contact"], user=setup["boss"])
    out = merge.render("<p>{{ confirm_link }}</p>", ctx)
    assert not out.blocked and PortalItem.objects.filter(kind="confirm_details").count() == 1


def test_the_starter_templates_point_to_the_portal():
    from apps.comms.models import MessageTemplate

    for key in ("accounts_records", "vat_records", "sa_records"):
        assert "{{ upload_link }}" in MessageTemplate.objects.get(key=key).body
    assert "{{ confirm_link }}" in MessageTemplate.objects.get(key="confirmation_statement").body
    ack = MessageTemplate.objects.get(key="request_acknowledgement")
    assert ack.active is False


def test_a_records_request_reminder_carries_the_upload_link():
    from apps.comms import services as comms
    from apps.comms.models import MessageTemplate

    cl = ClientFactory()
    portal_person(cl)
    task = make_task(None, client=cl)
    template = MessageTemplate.objects.get(key="vat_records")
    ctx = comms.build_context(cl, task=task)
    subject, html, text, problems = comms.render_template(template, ctx)
    del subject
    assert "/portal/items/" in html and "/portal/items/" in text
    assert not [p for p in problems if "upload" in p.lower()]
    assert len(mail.outbox) == 0
