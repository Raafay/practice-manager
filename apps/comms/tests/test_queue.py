import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, staff
from apps.clients.models import Client
from apps.comms import services
from apps.comms.models import QueuedMessage
from apps.core.models import PracticeSettings
from apps.events.models import ActivityEvent, Notification

from .factories import client_with_contact, make_template, queued

pytestmark = pytest.mark.django_db


def test_a_new_message_needs_approval_and_nothing_is_sent():
    client, _ = client_with_contact()
    message = queued(client, staff())
    assert message.state == QueuedMessage.State.NEEDS_APPROVAL
    assert mail.outbox == []
    assert services.send_due()["sent"] == 0
    assert mail.outbox == []


def test_approving_needs_the_right():
    client, _ = client_with_contact()
    message = queued(client)
    nobody = staff()
    nobody.extra_rights = []
    # Staff hold comms.approve by default; take it away through a role without it.
    from apps.accounts.models import Role

    role = Role.objects.create(name="Read only", slug="read-only", rights=[])
    nobody.role = role
    nobody.save()
    with pytest.raises(PermissionDenied):
        services.approve(message, nobody)
    approved = services.approve(message, manager())
    assert approved.state == QueuedMessage.State.APPROVED


def test_fee_messages_need_the_fee_right():
    from apps.accounts.models import Role
    from apps.comms.models import MessageTemplate

    client, _ = client_with_contact()
    template = make_template(group=MessageTemplate.Group.FEES)
    message = queued(client, template=template)
    plain = staff()
    plain.role = Role.objects.create(name="Approver", slug="approver", rights=["comms.approve"])
    plain.save()
    with pytest.raises(PermissionDenied):
        services.approve(message, plain)
    assert services.approve(message, owner()).state == "approved"


def test_a_message_with_no_address_cannot_be_approved():
    client, _ = client_with_contact()
    message = queued(client, to="")
    assert "No email address." in services.approval_problems(message)
    with pytest.raises(ValidationError):
        services.approve(message, manager())


def test_unknown_merge_fields_and_missing_links_block_approval():
    client, _ = client_with_contact()
    one = queued(client, body_html="<p>Hello {{ client.nmae }}</p>")
    two = queued(
        client,
        subject="B",
        body_html="<p>[Portal link link: not available yet]</p>",
        body_text="[Portal link: not available yet]",
    )
    assert any("Unfilled" in p for p in services.approval_problems(one))
    assert services.approval_problems(two)


def test_sending_uses_the_right_addresses():
    practice = PracticeSettings.load()
    practice.practice_name = "Sample Accountants"
    practice.sending_address = "office@example.com"
    practice.email = "info@example.com"
    practice.bcc_practice = True
    practice.save()
    client, _ = client_with_contact()
    writer = staff(name="Wendy Writer", email="wendy@example.com")
    approver = manager(name="Alan Approver", email="alan@example.com")
    message = queued(client, writer, bcc="audit@example.com")
    services.approve(message, approver)
    assert services.send_due() == {"sent": 1, "failed": 0}
    sent = mail.outbox[0]
    assert "office@example.com" in sent.from_email
    assert "Alan Approver" in sent.from_email
    assert sent.reply_to == ["alan@example.com"]
    assert sent.to == ["pat.sample@example.com"]
    assert sent.bcc == ["audit@example.com", "info@example.com"]
    message.refresh_from_db()
    assert message.state == "sent" and message.sent_at
    assert ActivityEvent.objects.filter(verb="message.sent", client=client).exists()


def test_no_bcc_when_the_setting_is_off():
    client, _ = client_with_contact()
    message = queued(client)
    services.approve(message, manager())
    services.send_due()
    assert mail.outbox[0].bcc == []


def test_signature_is_added_unless_switched_off():
    client, _ = client_with_contact()
    approver = manager(email_signature="Alan A, Sample Accountants")
    with_sig = queued(client, uses_signature=True)
    without = queued(client, subject="No sig", uses_signature=False)
    services.approve(with_sig, approver)
    services.approve(without, approver)
    services.send_due()
    bodies = {m.subject: m.body for m in mail.outbox}
    assert "Alan A, Sample Accountants" in bodies["A subject"]
    assert "Alan A" not in bodies["No sig"]


def test_the_pause_switch_holds_approved_messages():
    client, _ = client_with_contact()
    message = queued(client)
    services.approve(message, manager())
    services.set_paused(owner(), True)
    assert services.send_due()["paused"] is True
    assert mail.outbox == []
    message.refresh_from_db()
    assert message.state == "approved"
    services.set_paused(owner(), False)
    assert services.send_due()["sent"] == 1
    assert len(mail.outbox) == 1


def test_only_owner_and_managers_may_pause():
    with pytest.raises(PermissionDenied):
        services.set_paused(staff(), True)
    services.set_paused(manager(), True)
    assert services.is_paused()


def test_send_after_in_the_future_waits():
    from datetime import timedelta

    client, _ = client_with_contact()
    message = queued(client)
    services.approve(message, manager())
    message.send_after = timezone.now() + timedelta(hours=1)
    message.save()
    assert services.send_due()["sent"] == 0


def test_a_failed_send_is_recorded_notifies_and_can_be_retried(monkeypatch):
    client, _ = client_with_contact()
    approver = manager()
    message = queued(client)
    services.approve(message, approver)

    def boom(self, fail_silently=False):
        raise OSError("connection refused")

    monkeypatch.setattr("django.core.mail.EmailMultiAlternatives.send", boom)
    assert services.send_due() == {"sent": 0, "failed": 1}
    message.refresh_from_db()
    assert message.state == "failed"
    assert "connection refused" in message.error
    assert ActivityEvent.objects.filter(verb="message.failed", client=client).exists()
    assert Notification.objects.filter(user=approver, message__contains="failed").exists()

    monkeypatch.undo()
    services.retry(message, approver)
    assert services.send_due()["sent"] == 1
    message.refresh_from_db()
    assert message.state == "sent" and message.error == ""


def test_two_workers_never_send_the_same_message_twice():
    client, _ = client_with_contact()
    message = queued(client)
    services.approve(message, manager())
    first = QueuedMessage.objects.get(pk=message.pk)
    second = QueuedMessage.objects.get(pk=message.pk)
    services.send_one(first)
    services.send_one(second)
    assert len(mail.outbox) == 1


def test_cancelled_messages_are_not_sent():
    client, _ = client_with_contact()
    message = queued(client)
    services.cancel(message, manager())
    assert services.send_due()["sent"] == 0
    with pytest.raises(ValidationError):
        services.approve(message, manager())


def test_a_sent_message_cannot_be_cancelled():
    client, _ = client_with_contact()
    message = queued(client)
    services.approve(message, manager())
    services.send_due()
    message.refresh_from_db()
    with pytest.raises(ValidationError):
        services.cancel(message, manager())


def test_hand_written_message_to_a_former_client_warns_but_is_allowed_to_queue():
    client, _ = client_with_contact(status=Client.Status.FORMER)
    assert "former" in services.warning_for(client)
    # ...but approval is blocked: nothing goes to a former client.
    message = queued(client)
    with pytest.raises(ValidationError):
        services.approve(message, manager())


def test_html_is_cleaned_when_a_message_is_stored():
    client, _ = client_with_contact()
    message = queued(
        client, body_html="<p>Hi</p><script>alert(1)</script><img src=x onerror=alert(1)>"
    )
    assert "<script" not in message.body_html and "onerror" not in message.body_html
    assert "Hi" in message.body_html


def test_delivery_reports_update_the_message():
    client, _ = client_with_contact()
    message = queued(client)
    message.provider_message_id = "abc"
    message.save()
    assert services.record_delivery("abc", "bounced") == 1
    message.refresh_from_db()
    assert message.delivery_state == "bounced"
    assert services.record_delivery("abc", "nonsense") == 0


def test_the_same_duplicate_key_makes_one_message():
    client, _ = client_with_contact()
    a = queued(client, duplicate_key="k:1")
    b = queued(client, duplicate_key="k:1")
    assert a.pk == b.pk


def test_sensitive_documents_are_never_attached():
    from apps.clients.tests.factories import DocumentFactory

    client, _ = client_with_contact()
    safe = DocumentFactory(client=client)
    secret = DocumentFactory(client=client, sensitive=True)
    message = queued(client, attachments=[safe, secret])
    assert list(message.attachments.all()) == [safe]


def test_log_an_email_goes_on_the_timeline():
    from datetime import date

    client, _ = client_with_contact()
    services.log_email(
        owner(), client, on_date=date(2026, 10, 1), who_with="Pat Sample", summary="Asked about VAT"
    )
    assert ActivityEvent.objects.filter(verb="email.logged", client=client).exists()
    assert client.notes.filter(kind="email", text__contains="01/10/2026").exists()
