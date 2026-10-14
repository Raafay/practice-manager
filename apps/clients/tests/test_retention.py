"""Retention report, subject access export and removing a person (Stage 13, items 6-7).
Every person and company here is made up."""

import io
import json
import zipfile
from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import owner, sign_in, staff
from apps.aml.models import IdentityCheck
from apps.clients import retention
from apps.clients.models import Client, ClientContact, Contact, Document
from apps.clients.tests.factories import ClientFactory, ContactFactory, DocumentFactory

pytestmark = pytest.mark.django_db
TODAY = date(2026, 10, 14)


def former(name, *, kept_until, aml_until):
    return ClientFactory(
        name=name,
        status=Client.Status.FORMER,
        relationship_ended_on=date(2019, 1, 1),
        retain_until=kept_until,
        aml_retain_until=aml_until,
    )


@pytest.fixture
def world():
    gone = former("Long Gone Ltd", kept_until=date(2025, 1, 1), aml_until=date(2024, 1, 1))
    aml_due = former("Half Way Ltd", kept_until=date(2027, 1, 1), aml_until=date(2026, 1, 1))
    recent = former("Recent Ltd", kept_until=date(2031, 1, 1), aml_until=date(2030, 1, 1))
    live = ClientFactory(name="Still Here Ltd", status=Client.Status.ACTIVE)
    lost = ClientFactory(name="Never Signed Ltd", status=Client.Status.LOST)
    person_gone = ContactFactory(first_name="Robin", last_name="Gone")
    ClientContact.objects.create(client=gone, contact=person_gone, roles=["director"])
    person_live = ContactFactory(first_name="Kim", last_name="Kept")
    ClientContact.objects.create(client=live, contact=person_live, roles=["director"])
    # Kim was once a director of the gone client too: the live link keeps them.
    ClientContact.objects.create(client=gone, contact=person_live, roles=["director"])
    hidden = DocumentFactory(client=live, title="Old scan")
    Document.objects.filter(pk=hidden.pk).update(deleted_at=timezone.now() - timedelta(days=40))
    return {
        "gone": gone,
        "aml_due": aml_due,
        "recent": recent,
        "live": live,
        "lost": lost,
        "person_gone": person_gone,
        "person_live": person_live,
        "hidden": hidden,
    }


def test_the_report_lists_the_right_records(world):
    report = retention.build_report(TODAY)
    assert world["gone"] in report.clients and world["lost"] in report.clients
    assert world["recent"] not in report.clients and world["live"] not in report.clients
    assert report.aml_only == [world["aml_due"]]
    assert world["person_gone"] in report.people
    assert world["person_live"] not in report.people
    assert [d.pk for d in report.hidden_documents] == [world["hidden"].pk]


def test_the_report_and_its_job_delete_nothing(world):
    from apps.clients.jobs import retention_report

    counts = (Client.objects.count(), Contact.objects.count(), Document.objects.count())
    owner()  # someone to tell
    result = retention_report(None)
    assert result["clients"] >= 2
    assert (Client.objects.count(), Contact.objects.count(), Document.objects.count()) == counts


def test_the_report_page_is_for_the_owner(client, world):
    sign_in(client, staff())
    assert client.get(reverse("clients:retention")).status_code == 403
    sign_in(client, owner())
    page = client.get(reverse("clients:retention")).content.decode()
    assert "Long Gone Ltd" in page and "Robin Gone" in page
    clients_section = page.split('id="h-aml"')[0]
    assert "Still Here Ltd" not in clients_section


def test_the_subject_access_export_holds_everything(client, world):
    person = world["person_live"]
    person.ni_number = "ZZ 12 34 56 A"
    person.save()
    DocumentFactory(client=world["live"], contact=person, title="Passport")
    IdentityCheck.objects.create(client=world["live"], contact=person, state="verified")
    boss = owner()
    sign_in(client, boss)
    response = client.get(reverse("clients:contact_export", args=[person.pk]))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    data = json.loads(archive.read("person.json"))
    assert data["person"]["last_name"] == "Kept"
    assert data["person"]["ni_number"] == "ZZ 12 34 56 A"
    assert {c["client"] for c in data["clients"]} == {"Still Here Ltd", "Long Gone Ltd"}
    assert data["identity_checks"][0]["state"] == "Verified"
    assert any(name.startswith("files/") for name in archive.namelist())
    from apps.events.models import ActivityEvent

    assert ActivityEvent.objects.filter(verb="export.subject_access", actor=boss).exists()


def test_the_export_asks_for_the_password_again(client, world):
    sign_in(client, owner(), recent_password=False)
    response = client.get(reverse("clients:contact_export", args=[world["person_gone"].pk]))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("account_reauthenticate"))


def test_removing_a_person_is_blocked_while_a_client_keeps_them(client, world):
    sign_in(client, owner())
    person = world["person_live"]
    response = client.post(
        reverse("clients:contact_purge", args=[person.pk]), {"typed_name": person.full_name}
    )
    assert response.status_code == 422
    assert Contact.objects.filter(pk=person.pk).exists()


def test_removing_a_person_needs_their_name_typed(client, world):
    sign_in(client, owner())
    person = world["person_gone"]
    client.post(reverse("clients:contact_purge", args=[person.pk]), {"typed_name": "wrong"})
    assert Contact.objects.filter(pk=person.pk).exists()


def test_removing_a_person_takes_their_records_and_files(client, world):
    from apps.events.models import ActivityEvent

    person = world["person_gone"]
    passport = DocumentFactory(client=world["gone"], contact=person, title="Passport")
    stored = passport.file.name
    storage = passport.file.storage
    sign_in(client, owner())
    response = client.post(
        reverse("clients:contact_purge", args=[person.pk]), {"typed_name": person.full_name}
    )
    assert response.status_code == 302
    assert not Contact.objects.filter(pk=person.pk).exists()
    assert not Document.objects.filter(pk=passport.pk).exists()
    assert not storage.exists(stored)
    event = ActivityEvent.objects.get(verb="contact.purged")
    assert "Gone" not in event.summary and "Robin" not in event.summary
