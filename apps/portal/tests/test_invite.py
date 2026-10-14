"""Giving a contact portal access, and taking it away."""

import pytest
from django.core import mail
from django.test import Client as Browser
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.tests.factories import sign_in, staff
from apps.clients.models import ClientContact
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.events.models import ActivityEvent
from apps.portal import services

pytestmark = pytest.mark.django_db


def staff_browser():
    browser = Browser()
    sign_in(browser, staff())
    return browser


@pytest.fixture
def link():
    client = ClientFactory(name="Alpha Ltd")
    contact = ContactFactory(first_name="Sam", last_name="Sample", email="sam.sample@example.com")
    return ClientContactFactory(client=client, contact=contact, is_main=True)


def test_inviting_creates_a_portal_user_and_emails_the_address(
    link, django_capture_on_commit_callbacks
):
    browser = staff_browser()
    with django_capture_on_commit_callbacks(execute=True):
        response = browser.post(reverse("portal:invite", args=[link.client.pk, link.pk]))
    assert response.status_code == 302
    link.refresh_from_db()
    user = link.contact.portal_user
    assert link.portal_access and user.kind == User.Kind.PORTAL
    assert user.email == "sam.sample@example.com" and not user.has_usable_password()
    assert user.role is None
    assert len(mail.outbox) == 1 and "/portal/login/" in mail.outbox[0].body
    assert mail.outbox[0].to == ["sam.sample@example.com"]
    assert ActivityEvent.objects.filter(verb="portal.invited", client=link.client).exists()


def test_the_portal_state_goes_from_not_invited_to_invited_to_active(link, client):
    assert services.portal_state(link.client) == "not_invited"
    services.invite(staff(), link)
    assert services.portal_state(link.client) == "invited"
    user = link.contact.portal_user
    client.force_login(user)  # sets last_login
    user.refresh_from_db()
    from django.utils import timezone

    user.last_login = timezone.now()
    user.save()
    assert services.portal_state(link.client) == "active"
    page = staff_browser().get(reverse("clients:detail", args=[link.client.pk])).content.decode()
    assert "Portal: active" in page


def test_the_contacts_tab_offers_invite_and_withdraw(link):
    browser = staff_browser()
    url = reverse("clients:contacts", args=[link.client.pk])
    assert "Invite to portal" in browser.get(url).content.decode()
    services.invite(staff(), link)
    page = browser.get(url).content.decode()
    assert "Withdraw portal access" in page and "Invite to portal" not in page


def test_withdrawing_stops_access_at_once(link, client):
    services.invite(staff(), link)
    user = link.contact.portal_user
    client.force_login(user)
    assert client.get(reverse("portal:home")).status_code == 200
    staff_browser().post(reverse("portal:withdraw", args=[link.client.pk, link.pk]))
    assert client.get(reverse("portal:home")).status_code == 404
    assert ActivityEvent.objects.filter(verb="portal.withdrawn").exists()


def test_withdrawing_one_client_keeps_the_others(link, client):
    services.invite(staff(), link)
    other = ClientFactory(name="Bravo Ltd")
    second = ClientContact.objects.create(client=other, contact=link.contact, portal_access=True)
    user = link.contact.portal_user
    client.force_login(user)
    services.withdraw(staff(), link)
    page = client.get(reverse("portal:home")).content.decode()
    assert "Bravo Ltd" in page and "Alpha Ltd" not in page
    del second


def test_a_contact_without_an_email_cannot_be_invited():
    link = ClientContactFactory(contact=ContactFactory(email=""))
    browser = staff_browser()
    response = browser.post(reverse("portal:invite", args=[link.client.pk, link.pk]), follow=True)
    link.refresh_from_db()
    assert not link.portal_access and not User.objects.filter(kind="portal").exists()
    assert "no email address" in response.content.decode()


def test_an_email_that_belongs_to_a_staff_account_cannot_be_invited():
    person = staff()
    link = ClientContactFactory(contact=ContactFactory(email=person.email))
    browser = staff_browser()
    browser.post(reverse("portal:invite", args=[link.client.pk, link.pk]))
    link.refresh_from_db()
    assert not link.portal_access
    person.refresh_from_db()
    assert person.kind == "staff"


def test_inviting_twice_does_not_make_two_accounts(link):
    services.invite(staff(), link)
    services.invite(staff(), link)
    assert User.objects.filter(kind="portal").count() == 1
