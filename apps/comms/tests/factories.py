"""Helpers for comms tests. Everything here is invented."""

from datetime import date

from apps.clients.models import ClientContact
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.comms import services
from apps.comms.models import MessageTemplate, QueuedMessage
from apps.services.models import Deadline


def client_with_contact(email="pat.sample@example.com", **kwargs):
    client = ClientFactory(**kwargs)
    contact = ContactFactory(first_name="Pat", last_name="Sample", email=email)
    ClientContactFactory(client=client, contact=contact, is_main=True)
    return client, contact


def make_template(**kwargs) -> MessageTemplate:
    kwargs.setdefault("name", "Sample template")
    kwargs.setdefault("subject", "Hello {{ client.name }}")
    kwargs.setdefault(
        "body", "<p>Dear {{ contact.first_name }},</p><p>Due {{ deadline.due_date }}</p>"
    )
    return MessageTemplate.objects.create(**kwargs)


def make_deadline(
    client, *, rule="vat_return", due=date(2026, 11, 7), period_end=date(2026, 9, 30)
):
    return Deadline.objects.create(
        client=client,
        rule=rule,
        period_key=period_end.isoformat(),
        label="VAT return",
        period_end=period_end,
        due_date=due,
        original_due_date=due,
    )


def queued(client, user=None, **kwargs) -> QueuedMessage:
    kwargs.setdefault("to", "pat.sample@example.com")
    kwargs.setdefault("subject", "A subject")
    kwargs.setdefault("body_html", "<p>Body text</p>")
    return services.create_message(client, created_by=user, **kwargs)


__all__ = ["ClientContact"]
