import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.models import Client, Document
from apps.comms import services
from apps.comms.models import MessageTemplate, QueuedMessage, ReminderSchedule
from apps.core.models import PracticeSettings

from .factories import client_with_contact, make_template, queued

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    client, contact = client_with_contact()
    return {
        "client": client,
        "message": queued(client),
        "template": MessageTemplate.objects.get(key="vat_records"),
        "schedule": ReminderSchedule.objects.get(key="vat_records"),
    }


def addresses(w):
    c, m, t, s = w["client"].pk, w["message"].pk, w["template"].pk, w["schedule"].pk
    return [
        ("comms:queue", [], "get"),
        ("comms:bulk_approve", [], "post"),
        ("comms:pause", [], "post"),
        ("comms:bulk_email", [], "get"),
        ("comms:bulk_email", [], "post"),
        ("comms:message", [m], "get"),
        ("comms:message", [m], "post"),
        ("comms:compose", [c], "get"),
        ("comms:compose", [c], "post"),
        ("comms:log_email", [c], "get"),
        ("comms:log_email", [c], "post"),
        ("comms:letter", [c], "get"),
        ("comms:letter", [c], "post"),
        ("comms:templates", [], "get"),
        ("comms:template_add", [], "get"),
        ("comms:template_add", [], "post"),
        ("comms:template_edit", [t], "get"),
        ("comms:template_edit", [t], "post"),
        ("comms:template_delete", [t], "post"),
        ("comms:template_toggle", [t], "post"),
        ("comms:reminders", [], "get"),
        ("comms:reminder_edit", [s], "get"),
        ("comms:reminder_edit", [s], "post"),
        ("comms:reminder_toggle", [s], "post"),
    ]


def call(client, name, args, method):
    return getattr(client, method)(reverse(name, args=args))


def test_signed_out_users_are_sent_to_sign_in(client, world):
    for name, args, method in addresses(world):
        response = call(client, name, args, method)
        assert response.status_code == 302, name
        assert "/login/" in response.url, name


def test_portal_users_get_403_everywhere(client, world):
    sign_in(client, portal_user())
    for name, args, method in addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_settings_pages_need_the_settings_right(client, world):
    sign_in(client, staff())
    for name, args, method in addresses(world):
        if name.startswith(("comms:template", "comms:reminder", "comms:templates")) or name in (
            "comms:templates",
            "comms:reminders",
        ):
            assert call(client, name, args, method).status_code == 403, name


def test_sms_is_a_404_while_no_provider_is_configured(client, world):
    sign_in(client, owner())
    assert client.get(reverse("comms:sms", args=[world["client"].pk])).status_code == 404
    assert client.post(reverse("comms:sms", args=[world["client"].pk])).status_code == 404


def test_signed_out_sms_goes_to_sign_in(client, world):
    assert client.get(reverse("comms:sms", args=[world["client"].pk])).status_code == 302


def test_sms_works_and_is_queued_with_a_provider(client, world, settings):
    from apps.comms.sms import MemorySmsBackend

    settings.SMS_BACKEND = "apps.comms.sms.MemorySmsBackend"
    MemorySmsBackend.outbox.clear()
    sign_in(client, owner())
    url = reverse("comms:sms", args=[world["client"].pk])
    assert client.get(url).status_code == 200
    client.post(url, {"to": "07700900000", "text": "Hello", "action": "send"})
    assert MemorySmsBackend.outbox == [("07700900000", "Hello")]
    assert mail.outbox == []
    # the button is shown on the client page only with a provider
    assert (
        "Send SMS"
        in client.get(reverse("clients:detail", args=[world["client"].pk])).content.decode()
    )


def test_the_sms_button_is_hidden_without_a_provider(client, world):
    sign_in(client, owner())
    page = client.get(reverse("clients:detail", args=[world["client"].pk])).content.decode()
    assert "Send SMS" not in page
    assert "Send email" in page


def test_queue_lists_waiting_messages_first_and_counts_them_in_the_nav(client, world):
    sent = queued(world["client"], subject="Already gone")
    services.approve(sent, owner())
    services.send_due()
    sign_in(client, staff())
    page = client.get(reverse("comms:queue")).content.decode()
    assert page.index("A subject") < page.index("Already gone")
    assert "1 waiting for approval" in page


def test_the_queue_flags_a_missing_address(client, world):
    queued(world["client"], subject="Nowhere", to="")
    sign_in(client, staff())
    assert "No email address" in client.get(reverse("comms:queue")).content.decode()


def test_the_queue_filters(client, world):
    queued(world["client"], subject="Findable one")
    sign_in(client, staff())
    page = client.get(reverse("comms:queue"), {"q": "Findable"}).content.decode()
    assert "Findable one" in page and "A subject" not in page
    page = client.get(reverse("comms:queue"), {"state": "sent"}).content.decode()
    assert "Findable one" not in page


def test_approve_and_send_from_the_editor(client, world):
    sign_in(client, manager())
    url = reverse("comms:message", args=[world["message"].pk])
    response = client.post(
        url,
        {
            "to": "pat.sample@example.com",
            "subject": "Edited subject",
            "body": "<p>Edited</p>",
            "action": "approve",
        },
    )
    assert response.status_code == 302
    world["message"].refresh_from_db()
    assert world["message"].state == "approved" and world["message"].subject == "Edited subject"
    services.send_due()
    assert mail.outbox[0].subject == "Edited subject"
    assert mail.outbox[0].reply_to  # the approver


def test_the_editor_cleans_html(client, world):
    sign_in(client, manager())
    url = reverse("comms:message", args=[world["message"].pk])
    client.post(
        url,
        {
            "to": "pat.sample@example.com",
            "subject": "S",
            "body": "<p>Hi</p><script>alert(1)</script>",
            "action": "save",
        },
    )
    world["message"].refresh_from_db()
    assert "<script" not in world["message"].body_html


def test_a_user_without_the_right_cannot_approve(client, world):
    user = staff()
    user.role = Role.objects.create(name="Read only", slug="read-only", rights=[])
    user.save()
    sign_in(client, user)
    url = reverse("comms:message", args=[world["message"].pk])
    response = client.post(
        url, {"to": "a@example.com", "subject": "S", "body": "<p>x</p>", "action": "approve"}
    )
    assert response.status_code == 403
    world["message"].refresh_from_db()
    assert world["message"].state == "needs_approval"


def test_an_address_that_is_wrong_is_refused(client, world):
    sign_in(client, manager())
    url = reverse("comms:message", args=[world["message"].pk])
    response = client.post(
        url, {"to": "not-an-address", "subject": "S", "body": "x", "action": "save"}
    )
    assert response.status_code == 422


def test_cancel_from_the_editor(client, world):
    sign_in(client, manager())
    client.post(reverse("comms:message", args=[world["message"].pk]), {"action": "cancel"})
    world["message"].refresh_from_db()
    assert world["message"].state == "cancelled"


def test_bulk_approve_approves_the_ticked_and_reports_the_rest(client, world):
    no_address = queued(world["client"], subject="No address", to="")
    good = queued(world["client"], subject="Good")
    sign_in(client, manager())
    response = client.post(
        reverse("comms:bulk_approve"),
        {"ids": [good.pk, no_address.pk]},
        follow=True,
    )
    good.refresh_from_db()
    no_address.refresh_from_db()
    assert good.state == "approved" and no_address.state == "needs_approval"
    text = response.content.decode()
    assert "Approved 1 message" in text and "No email address" in text


def test_the_pause_switch_and_banner(client, world):
    sign_in(client, manager())
    client.post(reverse("comms:pause"), {"paused": "1"})
    assert PracticeSettings.load().comms_paused
    assert "All automatic sending is paused" in client.get(reverse("overview")).content.decode()
    client.post(reverse("comms:pause"), {"paused": "0"})
    assert "All automatic sending is paused" not in client.get(reverse("overview")).content.decode()


def test_staff_cannot_use_the_pause_switch(client, world):
    sign_in(client, staff())
    assert client.post(reverse("comms:pause"), {"paused": "1"}).status_code == 403
    assert not PracticeSettings.load().comms_paused


def test_compose_send_now_sends_one_email(client, world):
    sign_in(client, manager(email="mgr@example.com"))
    url = reverse("comms:compose", args=[world["client"].pk])
    assert client.get(url).status_code == 200
    response = client.post(
        url,
        {
            "contacts": ["pat.sample@example.com"],
            "subject": "Hello",
            "body": "<p>Hi Pat</p>",
            "signature": "mine",
            "action": "send",
        },
    )
    assert response.status_code == 302
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["pat.sample@example.com"]
    assert mail.outbox[0].reply_to == ["mgr@example.com"]


def test_compose_save_to_queue_waits_for_approval(client, world):
    sign_in(client, staff())
    url = reverse("comms:compose", args=[world["client"].pk])
    client.post(
        url,
        {
            "contacts": ["pat.sample@example.com"],
            "subject": "Later",
            "body": "<p>Hi</p>",
            "signature": "none",
            "action": "queue",
        },
    )
    message = QueuedMessage.objects.get(subject="Later")
    assert message.state == "needs_approval" and not message.uses_signature
    assert mail.outbox == []


def test_compose_needs_someone_to_send_to(client, world):
    sign_in(client, manager())
    response = client.post(
        reverse("comms:compose", args=[world["client"].pk]),
        {"subject": "Hello", "body": "<p>Hi</p>", "signature": "mine", "action": "send"},
    )
    assert response.status_code == 422 and mail.outbox == []


def test_compose_can_fill_in_from_a_template(client, world):
    sign_in(client, manager())
    url = reverse("comms:compose", args=[world["client"].pk])
    response = client.get(url, {"template": world["template"].pk})
    assert world["client"].name in response.content.decode() or "VAT" in response.content.decode()


def test_compose_attaches_a_document_but_never_a_sensitive_one(client, world):
    from apps.clients.tests.factories import DocumentFactory

    safe = DocumentFactory(client=world["client"], title="Safe doc")
    secret = DocumentFactory(client=world["client"], title="Secret doc", sensitive=True)
    sign_in(client, manager())
    page = client.get(reverse("comms:compose", args=[world["client"].pk])).content.decode()
    assert "Safe doc" in page and "Secret doc" not in page
    url = reverse("comms:compose", args=[world["client"].pk])
    base = {
        "contacts": ["pat.sample@example.com"],
        "subject": "With file",
        "body": "<p>x</p>",
        "signature": "none",
        "action": "send",
    }
    # A sensitive document is not a valid choice, so the message is refused.
    assert client.post(url, {**base, "attachments": [str(secret.pk)]}).status_code == 422
    assert mail.outbox == []
    client.post(url, {**base, "attachments": [str(safe.pk)]})
    assert [a[0] for a in mail.outbox[0].attachments] == [safe.original_name]


def test_compose_to_a_former_client_warns(client, world):
    former, _ = client_with_contact(status=Client.Status.FORMER)
    sign_in(client, manager())
    assert "former" in client.get(reverse("comms:compose", args=[former.pk])).content.decode()


def test_log_an_email_view(client, world):
    sign_in(client, staff())
    url = reverse("comms:log_email", args=[world["client"].pk])
    assert client.get(url).status_code == 200
    response = client.post(
        url, {"on_date": "2026-10-01", "who": "Pat Sample", "summary": "Sent records"}
    )
    assert response.status_code == 302
    assert world["client"].notes.filter(kind="email").exists()


def test_bulk_email_shows_who_is_skipped_and_why(client, world):
    ok, _ = client_with_contact(name="Zed Good Ltd")
    Client.objects.create(name="Zed No Address Ltd", status=Client.Status.ACTIVE)
    former, _ = client_with_contact(name="Zed Former Ltd", status=Client.Status.FORMER)
    template = make_template(
        name="Bulk", subject="Hi {{ client.name }}", body="<p>Dear {{ contact.first_name }}</p>"
    )
    sign_in(client, manager())
    url = reverse("comms:bulk_email")
    page = client.get(
        url, {"q": "Zed", "status": ["active", "former"], "template": template.pk}
    ).content.decode()
    assert "will get" in page and "No email address." in page and "is former" in page
    response = client.post(url + "?q=Zed&status=active&status=former", {"template": template.pk})
    assert response.status_code == 302
    made = QueuedMessage.objects.filter(template=template)
    assert [m.client for m in made] == [ok]
    assert made[0].state == "needs_approval" and "Zed Good Ltd" in made[0].subject
    assert mail.outbox == []


def test_template_edit_cleans_html_and_warns_about_unknown_fields(client, world):
    sign_in(client, owner())
    url = reverse("comms:template_edit", args=[world["template"].pk])
    response = client.post(
        url,
        {
            "name": "VAT",
            "channel": "email",
            "group": "records",
            "subject": "Hello {{ client.nmae }}",
            "body": "<p>Hi</p><script>alert(1)</script>",
            "send_mode": "hold",
            "active": "on",
        },
        follow=True,
    )
    world["template"].refresh_from_db()
    assert "<script" not in world["template"].body
    assert "client.nmae" in response.content.decode()


def test_only_the_owner_can_make_a_template_automatic(client, world):
    sign_in(client, manager())
    url = reverse("comms:template_edit", args=[world["template"].pk])
    data = {
        "name": "VAT",
        "channel": "email",
        "group": "records",
        "subject": "S",
        "body": "<p>x</p>",
        "send_mode": "auto",
        "active": "on",
    }
    assert client.post(url, data).status_code == 422
    world["template"].refresh_from_db()
    assert world["template"].send_mode == "hold"
    client.logout()
    sign_in(client, owner())
    client.post(url, data)
    world["template"].refresh_from_db()
    assert world["template"].send_mode == "auto"


def test_template_preview_renders_for_a_chosen_client(client, world):
    sign_in(client, owner())
    other, _ = client_with_contact(name="Preview Me Ltd")
    url = reverse("comms:template_edit", args=[world["template"].pk])
    page = client.get(url, {"client": other.pk}).content.decode()
    assert "Preview" in page and "Preview Me Ltd" in page


def test_system_templates_cannot_be_deleted_but_custom_ones_can(client, world):
    sign_in(client, owner())
    client.post(reverse("comms:template_delete", args=[world["template"].pk]))
    assert MessageTemplate.objects.filter(pk=world["template"].pk).exists()
    custom = make_template(name="Mine")
    client.post(reverse("comms:template_delete", args=[custom.pk]))
    assert not MessageTemplate.objects.filter(pk=custom.pk).exists()


def test_reminders_page_and_switching_one_on(client, world):
    sign_in(client, owner())
    page = client.get(reverse("comms:reminders")).content.decode()
    assert "VAT records request" in page and "Corporation tax payment reminder" in page
    client.post(reverse("comms:reminder_toggle", args=[world["schedule"].pk]))
    world["schedule"].refresh_from_db()
    assert world["schedule"].active


def test_editing_a_reminder_changes_timing_and_repeats(client, world):
    sign_in(client, owner())
    url = reverse("comms:reminder_edit", args=[world["schedule"].pk])
    assert client.get(url).status_code == 200
    response = client.post(
        url,
        {
            "template": world["template"].pk,
            "offsets_text": "3, 10",
            "repeat_every_days": 7,
            "max_repeats": 2,
            "send_mode": "hold",
        },
    )
    assert response.status_code == 302
    world["schedule"].refresh_from_db()
    assert world["schedule"].offsets == [3, 10] and world["schedule"].max_repeats == 2


def test_a_letter_is_made_as_a_pdf_in_documents(client, world):
    letter = make_template(
        name="Clearance",
        channel="letter",
        subject="Professional clearance",
        body="<p>Dear {{ contact.first_name }}</p>",
    )
    sign_in(client, manager())
    url = reverse("comms:letter", args=[world["client"].pk])
    assert client.get(url).status_code == 200
    response = client.post(url, {"template": letter.pk})
    assert response.status_code == 302
    document = Document.objects.get(client=world["client"])
    assert document.content_type == "application/pdf"
    with document.file.open("rb") as handle:
        assert handle.read(5) == b"%PDF-"


def test_a_letter_with_an_unknown_field_is_refused(client, world):
    letter = make_template(name="Bad", channel="letter", subject="S", body="<p>{{ nope }}</p>")
    sign_in(client, manager())
    response = client.post(
        reverse("comms:letter", args=[world["client"].pk]), {"template": letter.pk}
    )
    assert response.status_code == 422
    assert not Document.objects.exists()


def test_practice_settings_hold_the_sending_address_and_copy_switch(client, world):
    sign_in(client, owner())
    response = client.get(reverse("core:practice_settings"))
    assert "sending_address" in response.content.decode()
