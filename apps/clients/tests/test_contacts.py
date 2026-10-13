import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.tests.factories import sign_in, staff
from apps.clients.models import Client, ClientContact, ClientLink, Contact
from apps.events.models import ActivityEvent

from .factories import ClientContactFactory, ClientFactory, ContactFactory

pytestmark = pytest.mark.django_db


def test_the_first_person_linked_becomes_the_main_contact(client):
    target = ClientFactory()
    sign_in(client, staff())
    client.post(
        reverse("clients:contact_add", args=[target.pk]),
        {"first_name": "Una", "last_name": "First", "email": "una@example.com"},
    )
    client.post(
        reverse("clients:contact_add", args=[target.pk]),
        {"first_name": "Dee", "last_name": "Second", "email": "dee@example.com"},
    )
    mains = ClientContact.objects.filter(client=target, is_main=True)
    assert [m.contact.first_name for m in mains] == ["Una"]


def test_choosing_a_new_main_contact_replaces_the_old_one(client):
    target = ClientFactory()
    old = ClientContactFactory(client=target, is_main=True)
    new = ClientContactFactory(client=target)
    sign_in(client, staff())
    response = client.post(
        reverse("clients:contact_edit", args=[target.pk, new.pk]),
        {"roles": ["director"], "is_main": "on", "receives_reminders": "on"},
    )
    assert response.status_code == 302
    old.refresh_from_db()
    new.refresh_from_db()
    assert new.is_main and not old.is_main
    assert new.roles == ["director"]
    assert ClientContact.objects.filter(client=target, is_main=True).count() == 1


def test_the_database_refuses_two_main_contacts(db):
    target = ClientFactory()
    ClientContactFactory(client=target, is_main=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        ClientContactFactory(client=target, is_main=True)


def test_the_same_person_cannot_be_linked_twice_to_a_client():
    link = ClientContactFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        ClientContact.objects.create(client=link.client, contact=link.contact)


def test_adding_a_contact_offers_the_person_already_on_file(client):
    target = ClientFactory()
    existing = ContactFactory(first_name="Eve", last_name="Exists", email="eve@example.com")
    sign_in(client, staff())
    # The search offers them.
    found = client.get(
        reverse("clients:contact_add", args=[target.pk]), {"q": "exist", "matches": "1"}
    )
    assert b"Eve Exists" in found.content
    # Creating a duplicate by email is stopped until the user says it really is someone else.
    response = client.post(
        reverse("clients:contact_add", args=[target.pk]),
        {"first_name": "Evelyn", "last_name": "Different", "email": "EVE@example.com"},
    )
    assert response.status_code == 422
    assert b"Eve Exists" in response.content and b"confirm_new" in response.content
    assert Contact.objects.count() == 1
    # Or by name.
    response = client.post(
        reverse("clients:contact_add", args=[target.pk]),
        {"first_name": "eve", "last_name": "EXISTS", "email": "other@example.com"},
    )
    assert response.status_code == 422
    # Linking the existing person adds no second record.
    client.post(reverse("clients:contact_link", args=[target.pk, existing.pk]))
    assert Contact.objects.count() == 1
    assert ClientContact.objects.filter(client=target, contact=existing).exists()
    # A genuinely different person can still be created on confirmation.
    other = ClientFactory()
    client.post(
        reverse("clients:contact_add", args=[other.pk]),
        {
            "first_name": "Eve",
            "last_name": "Exists",
            "email": "eve@example.com",
            "confirm_new": "1",
        },
    )
    assert Contact.objects.count() == 2


def test_people_already_linked_are_not_offered_again(client):
    link = ClientContactFactory(contact__first_name="Already", contact__last_name="Here")
    sign_in(client, staff())
    found = client.get(
        reverse("clients:contact_add", args=[link.client.pk]), {"q": "already", "matches": "1"}
    )
    assert b"Already Here" not in found.content


def test_unlinking_keeps_the_person_and_their_other_clients(client):
    person = ContactFactory()
    one, two = ClientFactory(), ClientFactory()
    link_one = ClientContactFactory(client=one, contact=person)
    ClientContactFactory(client=two, contact=person)
    sign_in(client, staff())
    client.post(reverse("clients:contact_unlink", args=[one.pk, link_one.pk]))
    assert Contact.objects.filter(pk=person.pk).exists()
    assert not ClientContact.objects.filter(client=one).exists()
    assert ClientContact.objects.filter(client=two, contact=person).exists()
    assert ActivityEvent.objects.filter(verb="contact.unlinked", client=one).exists()


def test_a_link_cannot_be_reached_through_another_client(client):
    one, two = ClientFactory(), ClientFactory()
    link = ClientContactFactory(client=two)
    sign_in(client, staff())
    assert client.post(reverse("clients:contact_unlink", args=[one.pk, link.pk])).status_code == 404
    assert client.get(reverse("clients:contact_edit", args=[one.pk, link.pk])).status_code == 404


def test_contact_page_shows_every_client_the_person_is_linked_to(client):
    person = ContactFactory(first_name="Shared", last_name="Person")
    one, two = ClientFactory(name="First Ltd"), ClientFactory(name="Second Ltd")
    ClientContactFactory(client=one, contact=person, is_main=True, roles=["director"])
    ClientContactFactory(client=two, contact=person, roles=["shareholder"])
    sign_in(client, staff())
    page = client.get(reverse("clients:contact_detail", args=[person.pk])).content.decode()
    assert "First Ltd" in page and "Second Ltd" in page and "Director" in page


def test_contact_secrets_are_masked_and_show_is_logged(client):
    person = ContactFactory(ni_number="QQ123456C", personal_utr="1234567890")
    link = ClientContactFactory(contact=person)
    viewer = staff()
    sign_in(client, viewer)
    page = client.get(reverse("clients:contact_detail", args=[person.pk])).content.decode()
    assert "QQ123456C" not in page and "••••••56C" in page
    assert "1234567890" not in page
    edit = client.get(reverse("clients:contact_detail_edit", args=[person.pk])).content.decode()
    assert "QQ123456C" not in edit
    revealed = client.post(
        reverse("clients:contact_reveal", args=[person.pk, "ni_number"]), {"client": link.client.pk}
    )
    assert b"QQ123456C" in revealed.content
    event = ActivityEvent.objects.get(verb="sensitive.revealed")
    assert event.actor == viewer and event.client == link.client
    assert "QQ123456C" not in event.summary and "QQ123456C" not in str(event.data)
    assert (
        client.post(reverse("clients:contact_reveal", args=[person.pk, "email"])).status_code == 403
    )


def test_editing_a_person_validates_and_logs_on_each_client(client):
    person = ContactFactory()
    one, two = ClientFactory(), ClientFactory()
    ClientContactFactory(client=one, contact=person)
    ClientContactFactory(client=two, contact=person)
    sign_in(client, staff())
    base = {"first_name": person.first_name, "last_name": person.last_name, "email": person.email}
    bad = client.post(
        reverse("clients:contact_detail_edit", args=[person.pk]), {**base, "ni_number": "NOT-AN-NI"}
    )
    assert bad.status_code == 422
    ok = client.post(
        reverse("clients:contact_detail_edit", args=[person.pk]),
        {**base, "ni_number": "qq 12 34 56 c", "mobile": "07700 900123"},
    )
    assert ok.status_code == 302
    person.refresh_from_db()
    assert person.ni_number == "QQ123456C"
    events = ActivityEvent.objects.filter(verb="contact.changed")
    assert {e.client_id for e in events} == {one.pk, two.pk}
    assert all("QQ123456C" not in str(e.data) for e in events)


def test_create_personal_tax_client_links_the_two(client):
    company = ClientFactory(name="Owner Co Ltd", manager=staff())
    person = ContactFactory(first_name="Olive", last_name="Owner", email="olive@example.com")
    ClientContactFactory(client=company, contact=person, is_main=True)
    sign_in(client, staff())
    response = client.post(
        reverse("clients:personal_tax_client", args=[person.pk]), {"client": company.pk}
    )
    personal = Client.objects.get(client_type="individual")
    assert response["Location"] == reverse("clients:detail", args=[personal.pk])
    assert personal.name == "Olive Owner" and personal.main_contact == person
    assert personal.manager == company.manager
    link = ClientLink.objects.get()
    assert {link.client_a, link.client_b} == {company, personal}
    assert link.relationship == "personal_tax"
    # A second attempt is refused rather than making a duplicate.
    client.post(reverse("clients:personal_tax_client", args=[person.pk]), {"client": company.pk})
    assert Client.objects.filter(client_type="individual").count() == 1


def test_links_show_on_both_clients_and_cannot_repeat_or_point_at_self(client):
    one, two = ClientFactory(name="One Ltd"), ClientFactory(name="Two Ltd")
    sign_in(client, staff())
    response = client.post(
        reverse("clients:link_add", args=[one.pk]),
        {"other": two.pk, "relationship": "group", "note": "Same group"},
    )
    assert response.status_code == 302
    assert b"Two Ltd" in client.get(reverse("clients:links", args=[one.pk])).content
    assert b"One Ltd" in client.get(reverse("clients:links", args=[two.pk])).content
    # Adding from the other side is a duplicate.
    again = client.post(
        reverse("clients:link_add", args=[two.pk]), {"other": one.pk, "relationship": "other"}
    )
    assert again.status_code == 422
    assert (
        client.post(
            reverse("clients:link_add", args=[one.pk]), {"other": one.pk, "relationship": "other"}
        ).status_code
        == 422
    )
    assert ClientLink.objects.count() == 1
    link = ClientLink.objects.get()
    client.post(reverse("clients:link_remove", args=[two.pk, link.pk]))
    assert not ClientLink.objects.exists() and Client.objects.count() == 2
    assert ActivityEvent.objects.filter(verb="link.added").count() == 2


def test_link_search_offers_matching_clients_but_not_itself(client):
    one, two = ClientFactory(name="Alpha Ltd"), ClientFactory(name="Alpine Ltd")
    sign_in(client, staff())
    found = client.get(
        reverse("clients:link_add", args=[one.pk]), {"q": "alp", "matches": "1"}
    ).content
    assert b"Alpine Ltd" in found and b"Alpha Ltd" not in found
    assert two.pk
