"""Shared test setup for the portal. Everything here is invented."""

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.clients.models import ClientContact
from apps.clients.tests.factories import ClientFactory, ContactFactory

PDF = b"%PDF-1.4\n% made up test file\n"


def pdf_upload(name="records.pdf", data=PDF):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


def portal_person(client=None, *, email=None, main=True, can_sign=False, access=True, **extra):
    """A contact with a portal user and a link to a client. Returns (user, contact, link)."""
    client = client or ClientFactory()
    contact = ContactFactory(**({"email": email} if email else {}), **extra)
    user = User.objects.create_user(
        contact.email, name=contact.full_name, kind=User.Kind.PORTAL, role=None
    )
    contact.portal_user = user
    contact.save()
    link = ClientContact.objects.create(
        client=client,
        contact=contact,
        is_main=main,
        can_sign=can_sign,
        portal_access=access,
        roles=["director"],
    )
    return user, contact, link


def portal_login(http, user):
    http.force_login(user)
    return http
