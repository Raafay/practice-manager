"""Requests: the public link, the portal form, logging by hand, and the inbox."""

import datetime

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as Browser
from django.urls import reverse

from apps.accounts.tests.factories import manager, sign_in, staff
from apps.clients.models import Document
from apps.clients.tests.factories import ClientFactory
from apps.comms.models import MessageTemplate, QueuedMessage
from apps.core.dates import add_working_days
from apps.events.models import ActivityEvent, Notification
from apps.portal import requests as services
from apps.portal.models import Request
from apps.portal.tests.helpers import PDF, pdf_upload, portal_login, portal_person
from apps.tasks import services as task_services
from apps.tasks.models import TaskCategory, TaskDocument, TaskKind
from apps.tasks.tests.factories import make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def cl():
    return ClientFactory(name="Alpha Ltd", manager=manager())


def post_form(http, token, **overrides):
    data = {
        "name": "Pat Sample",
        "email": "pat@example.com",
        "phone": "",
        "body": "Please can you send me last year's accounts?",
        "urgency": "normal",
        "website": "",
    }
    data.update(overrides)
    extra = data.pop("_extra", {})
    return http.post(reverse("portal:request_form", args=[token]), data, **extra)


def category():
    return (
        TaskCategory.objects.filter(kind=TaskKind.REQUEST).first() or TaskCategory.objects.first()
    )


def staff_browser():
    browser = Browser()
    sign_in(browser, staff())
    return browser


# ---------------------------------------------------------------- the request link


def test_the_form_creates_a_request_and_tells_the_manager(client, cl):
    token = services.ensure_token(cl)
    response = post_form(client, token, urgency="urgent", files=[pdf_upload()])
    req = Request.objects.get()
    assert response.status_code == 302 and response.url.endswith(f"/thanks/?ref={req.reference}")
    assert (req.client, req.channel, req.state) == (cl, "form", "new")
    assert req.sender_name == "Pat Sample" and req.urgency == "urgent"
    assert req.files.count() == 1 and req.files.get().file.name.startswith("requests/")
    assert Notification.objects.filter(user=cl.manager, message__contains="request").exists()
    assert ActivityEvent.objects.filter(verb="request.received", client=cl).exists()
    thanks = client.get(response.url).content.decode()
    assert req.reference in thanks and "Alpha Ltd" in thanks


def test_the_form_needs_the_basics(client, cl):
    token = services.ensure_token(cl)
    for bad in ({"name": ""}, {"email": "nope"}, {"body": ""}):
        assert post_form(client, token, **bad).status_code == 422
    assert not Request.objects.exists()


def test_file_rules(client, cl):
    token = services.ensure_token(cl)
    four = [pdf_upload(f"f{i}.pdf") for i in range(4)]
    assert post_form(client, token, files=four).status_code == 422
    big = SimpleUploadedFile(
        "big.pdf", PDF + b"0" * (10 * 1024 * 1024), content_type="application/pdf"
    )
    assert post_form(client, token, files=[big]).status_code == 422
    exe = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
    assert post_form(client, token, files=[exe]).status_code == 422
    fake = SimpleUploadedFile("fake.pdf", b"not really", content_type="application/pdf")
    assert post_form(client, token, files=[fake]).status_code == 422
    assert not Request.objects.exists()
    three = [pdf_upload(f"f{i}.pdf") for i in range(3)]
    assert post_form(client, token, files=three).status_code == 302
    assert Request.objects.get().files.count() == 3


def test_the_bot_trap_keeps_nothing_and_looks_like_success(client, cl):
    token = services.ensure_token(cl)
    response = post_form(client, token, website="http://spam.example")
    assert response.status_code == 302
    assert not Request.objects.exists()
    assert ActivityEvent.objects.filter(verb="request.bot_trapped").exists()


def test_the_hidden_field_is_not_visible_to_people(client, cl):
    page = client.get(
        reverse("portal:request_form", args=[services.ensure_token(cl)])
    ).content.decode()
    assert 'name="website"' in page and "hp-wrap" in page and 'tabindex="-1"' in page


def test_ten_an_hour_per_address(client, cl):
    token = services.ensure_token(cl)
    codes = [post_form(client, token).status_code for _ in range(11)]
    assert codes[:10] == [302] * 10 and codes[10] == 429
    assert Request.objects.count() == 10
    # Another address is not held up.
    other = post_form(client, token, _extra={"REMOTE_ADDR": "10.9.9.9"})
    assert other.status_code == 302


def test_thirty_a_day_per_link(client, cl):
    token = services.ensure_token(cl)
    codes = []
    for n in range(31):
        codes.append(
            post_form(client, token, _extra={"REMOTE_ADDR": f"10.1.0.{n + 1}"}).status_code
        )
    assert codes[:30] == [302] * 30 and codes[30] == 429


def test_replacing_the_link_kills_the_old_one(client, cl):
    old = services.ensure_token(cl)
    assert client.get(reverse("portal:request_form", args=[old])).status_code == 200
    browser = staff_browser()
    response = browser.post(reverse("portal:replace_link", args=[cl.pk]))
    assert response.status_code == 302
    cl.refresh_from_db()
    assert cl.request_token != old
    assert client.get(reverse("portal:request_form", args=[old])).status_code == 404
    assert post_form(client, old).status_code == 404
    assert client.get(reverse("portal:request_form", args=[cl.request_token])).status_code == 200
    assert ActivityEvent.objects.filter(verb="request.link_replaced", client=cl).exists()


def test_the_tab_shows_the_link_a_copy_button_and_a_qr_code(cl):
    token = services.ensure_token(cl)
    page = staff_browser().get(reverse("portal:client_requests", args=[cl.pk])).content.decode()
    assert f"/r/{token}/" in page and "data-copy-from" in page and "<svg" in page
    assert "Replace link" in page


def test_an_archived_client_link_does_not_work(client, cl):
    token = services.ensure_token(cl)
    from django.utils import timezone

    cl.archived_at = timezone.now()
    cl.save()
    assert client.get(reverse("portal:request_form", args=[token])).status_code == 404


# ---------------------------------------------------------------- the acknowledgement


def test_the_acknowledgement_is_off_by_default_and_queues_when_on(client, cl):
    token = services.ensure_token(cl)
    post_form(client, token)
    assert QueuedMessage.objects.count() == 0
    MessageTemplate.objects.filter(key="request_acknowledgement").update(active=True)
    post_form(client, token)
    message = QueuedMessage.objects.get()
    assert message.state == "needs_approval" and message.to == "pat@example.com"
    assert Request.objects.latest("id").reference in message.subject
    assert len(mail.outbox) == 0  # nothing leaves without approval


# ---------------------------------------------------------------- from the portal


def test_a_portal_request(client, cl):
    user, contact, _ = portal_person(cl)
    portal_login(client, user)
    response = client.post(
        reverse("portal:request_new"),
        {"subject": "A change of address", "body": "We moved.", "urgency": "normal"},
    )
    req = Request.objects.get()
    assert response.status_code == 302 and req.channel == "portal" and req.contact == contact
    assert req.sender_email == user.email
    assert "A change of address" in client.get(reverse("portal:requests")).content.decode()
    assert client.get(response.url).status_code == 200


# ---------------------------------------------------------------- the inbox


def make_request(cl=None, **kwargs):
    kwargs.setdefault("channel", "form")
    kwargs.setdefault("subject", "Send me the accounts")
    kwargs.setdefault("body", "Please send the last accounts.")
    kwargs.setdefault("sender_name", "Pat Sample")
    kwargs.setdefault("sender_email", "pat@example.com")
    return services.create_request(client=cl, notify=False, **kwargs)


def test_converting_makes_a_request_task_with_a_date_three_working_days_ahead(cl):
    req = make_request(cl, uploads=[pdf_upload("statement.pdf")])
    owner = staff()
    browser = Browser()
    sign_in(browser, owner)
    from django.utils import timezone

    expected = add_working_days(timezone.localdate(), 3)
    response = browser.post(
        reverse("portal:inbox_convert", args=[req.pk]),
        {
            "title": "Send the accounts",
            "category": category().pk,
            "owner": owner.pk,
            "target_date": expected.isoformat(),
        },
    )
    assert response.status_code == 302
    req.refresh_from_db()
    task = req.task
    assert task.kind == "request" and task.client == cl and task.target_date == expected
    assert req.state == "in_progress" and task.owner == owner
    assert "last accounts" in task.description
    doc = Document.objects.get(client=cl, source="request")
    assert doc.original_name == "statement.pdf"
    assert TaskDocument.objects.filter(task=task, document=doc).count() == 1
    assert req.files.get().document == doc


def test_the_convert_form_defaults_to_three_working_days(cl):
    from django.utils import timezone

    req = make_request(cl)
    page = staff_browser().get(reverse("portal:inbox_convert", args=[req.pk])).content.decode()
    assert add_working_days(timezone.localdate(), 3).isoformat() in page


def test_a_request_with_no_client_must_be_given_one_to_convert(cl):
    req = make_request(None)
    owner = staff()
    browser = Browser()
    sign_in(browser, owner)
    data = {"title": "T", "category": category().pk, "owner": owner.pk, "target_date": "2026-11-01"}
    assert browser.post(reverse("portal:inbox_convert", args=[req.pk]), data).status_code == 422
    data["client_text"] = f"{cl.name} ({cl.reference})"
    assert browser.post(reverse("portal:inbox_convert", args=[req.pk]), data).status_code == 302
    req.refresh_from_db()
    assert req.client == cl and req.task is not None


def test_a_request_closes_when_its_task_is_done(cl):
    req = make_request(cl)
    task = services.convert_to_task(
        staff(), req, category=category(), owner=staff(), target_date=datetime.date(2026, 12, 1)
    )
    req.refresh_from_db()
    assert req.state == "in_progress"
    task_services.complete(staff(), task)
    req.refresh_from_db()
    assert req.state == "closed" and req.closed_at


def test_linking_to_an_existing_task(cl):
    req = make_request(cl)
    task = make_task(staff(), client=cl)
    browser = staff_browser()
    response = browser.post(reverse("portal:inbox_link", args=[req.pk]), {"task": task.pk})
    assert response.status_code == 302
    req.refresh_from_db()
    assert req.task == task and req.state == "in_progress"
    # A task of another client is refused.
    other = make_task(staff(), client=ClientFactory())
    req2 = make_request(cl)
    response = browser.post(reverse("portal:inbox_link", args=[req2.pk]), {"task": other.pk})
    assert response.status_code == 422
    req2.refresh_from_db()
    assert req2.task is None


def test_reply_by_email_goes_into_the_queue(cl):
    req = make_request(cl)
    response = staff_browser().post(
        reverse("portal:inbox_reply", args=[req.pk]),
        {"to": "pat@example.com", "subject": "Re: accounts", "body": "Attached.\nThanks."},
    )
    assert response.status_code == 302
    message = QueuedMessage.objects.get()
    assert message.state == "needs_approval" and "Attached." in message.body_html
    assert len(mail.outbox) == 0
    req.refresh_from_db()
    assert req.state == "answered"


def test_close_needs_a_note_and_spam_and_reopen(cl):
    req = make_request(cl)
    browser = staff_browser()
    url = reverse("portal:inbox_close", args=[req.pk])
    assert browser.post(url, {"note": ""}).status_code == 422
    assert browser.post(url, {"note": "Done by phone."}).status_code == 302
    req.refresh_from_db()
    assert req.state == "closed" and req.closing_note == "Done by phone."
    browser.post(reverse("portal:inbox_reopen", args=[req.pk]))
    req.refresh_from_db()
    assert req.state == "new" and not req.closing_note
    browser.post(reverse("portal:inbox_spam", args=[req.pk]))
    req.refresh_from_db()
    assert req.state == "spam"


def test_the_inbox_lists_new_first_and_the_nav_counts_them(cl):
    old = make_request(cl, subject="Closed one")
    services.close(staff(), old, "done")
    new = make_request(cl, subject="Fresh one")
    browser = staff_browser()
    page = browser.get(reverse("portal:inbox") + "?state=all").content.decode()
    assert page.index("Fresh one") < page.index("Closed one")
    overview = browser.get(reverse("overview")).content.decode()
    assert 'aria-label="1 new"' in overview and "Fresh one" in overview
    del new


def test_logging_by_hand_and_log_and_create_task(cl):
    owner = staff()
    browser = Browser()
    sign_in(browser, owner)
    data = {
        "channel": "whatsapp",
        "client_text": f"{cl.name} ({cl.reference})",
        "sender_name": "Pat Sample",
        "body": "Hi can you send the VAT return copy",
        "urgency": "normal",
    }
    response = browser.post(reverse("portal:inbox_log"), data)
    req = Request.objects.get()
    assert response.status_code == 302
    assert (req.channel, req.client, req.logged_by) == ("whatsapp", cl, owner) and req.task is None
    both = dict(data, log_task="1", category=category().pk, owner=owner.pk, body="Second message")
    browser.post(reverse("portal:inbox_log"), both)
    second = Request.objects.get(body="Second message")
    assert second.task is not None and second.state == "in_progress"
    # "Log and create task" with no client is refused.
    nobody = dict(both, client_text="")
    assert browser.post(reverse("portal:inbox_log"), nobody).status_code == 422


def test_a_general_request_can_be_logged_with_no_client():
    browser = staff_browser()
    browser.post(
        reverse("portal:inbox_log"),
        {"channel": "phone", "body": "Asked about opening hours", "urgency": "normal"},
    )
    req = Request.objects.get()
    assert req.client is None and req.channel == "phone"


def test_log_a_request_is_in_the_new_menu(cl):
    page = staff_browser().get(reverse("overview")).content.decode()
    assert reverse("portal:inbox_log") in page


def test_a_proposal_question_also_lands_in_the_inbox():
    from apps.pipeline import proposals
    from apps.pipeline.tests.test_proposals import sent_proposal

    cl, proposal, link = sent_proposal()
    proposals.ask_question(link, text="Is the fee fixed for the first year?")
    req = Request.objects.get()
    assert req.client == cl and req.proposal_id == proposal.pk
    assert "fixed for the first year" in req.body and req.state == "new"
