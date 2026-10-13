import copy
from datetime import date

import pytest

from apps.accounts.tests.factories import manager, owner
from apps.clients.models import Client, ClientContact, Contact
from apps.clients.tests.factories import ClientFactory, ContactFactory
from apps.companieshouse import jobs, services
from apps.companieshouse.models import CompanySnapshot
from apps.events.models import ActivityEvent, Notification
from apps.jobs.services import run_job

pytestmark = pytest.mark.django_db

TUESDAY = date(2026, 10, 13)
SUNDAY = date(2026, 10, 18)


def ch_events(client):
    return ActivityEvent.objects.filter(client=client, verb__startswith="companieshouse.")


def test_adding_a_company_creates_the_client_contacts_and_links():
    boss = owner()
    client, result = services.import_company(boss, "9999901")
    assert client.name == "EXAMPLE TRADING LTD"
    assert client.client_type == Client.Type.LTD
    assert client.company_number == "09999901"
    assert client.next_accounts_due == date(2026, 12, 31)
    assert client.next_statement_due == date(2026, 11, 3)
    assert client.last_accounts_made_up_to == date(2025, 3, 31)
    assert (client.accounting_ref_day, client.accounting_ref_month) == (31, 3)
    assert client.registered_office.startswith("1 Example Street\nUnit 2\nSampletown")
    assert client.sic_codes == "47910, 62020"
    assert client.last_synced_at is not None
    # Two people: Alice (director and owner) and Robert (secretary). Corporates are not contacts.
    links = {link.contact.full_name: link for link in client.client_contacts.all()}
    assert set(links) == {"Alice Sample", "Robert Tester"}
    assert links["Alice Sample"].roles == ["director", "psc"]
    assert links["Alice Sample"].source == ClientContact.Source.COMPANIES_HOUSE
    assert links["Alice Sample"].appointed_on == date(2015, 3, 12)
    assert links["Robert Tester"].roles == ["secretary"]
    alice = links["Alice Sample"].contact
    assert alice.ch_officer_id == "AAA111OFF"
    assert (alice.birth_month, alice.birth_year) == (6, 1980)
    assert alice.ch_identity_verified and alice.ch_identity_verified_on == date(2026, 1, 15)
    assert result.contacts_created == 2
    snapshot = CompanySnapshot.objects.get(client=client)
    assert len(snapshot.officers) == 3 and len(snapshot.owners) == 2 and len(snapshot.filings) == 3
    assert ch_events(client).filter(verb="companieshouse.imported").count() == 1


def test_adding_the_same_company_again_creates_nothing_new():
    boss = owner()
    first, _ = services.import_company(boss, "09999901")
    counts = (Client.objects.count(), Contact.objects.count(), ClientContact.objects.count())
    event_count = ActivityEvent.objects.count()
    second, result = services.import_company(boss, "09999901")
    assert second.pk == first.pk
    assert (
        Client.objects.count(),
        Contact.objects.count(),
        ClientContact.objects.count(),
    ) == counts
    assert result.changes == [] and result.contacts_created == 0
    assert ActivityEvent.objects.count() == event_count


def test_an_existing_contact_is_matched_by_officer_id():
    known = ContactFactory(first_name="Ally", last_name="Sample-Old", ch_officer_id="AAA111OFF")
    client, result = services.import_company(owner(), "09999901")
    assert client.client_contacts.filter(contact=known).exists()
    assert not Contact.objects.filter(first_name="Alice", last_name="Sample").exists()
    assert result.contacts_created == 1  # only Robert


def test_an_existing_contact_is_matched_by_name_and_birth_month_and_year():
    known = ContactFactory(first_name="Robert", last_name="Tester", date_of_birth=date(1975, 2, 9))
    other = ContactFactory(first_name="Alice", last_name="Sample", birth_month=1, birth_year=1980)
    client, _ = services.import_company(owner(), "09999901")
    assert client.client_contacts.filter(contact=known).exists()
    known.refresh_from_db()
    assert known.ch_officer_id == "AAA222OFF"
    # Same name, different birth month: a different person.
    assert not client.client_contacts.filter(contact=other).exists()


def test_fill_in_an_existing_client_by_its_number():
    client = ClientFactory(name="Our name for it", company_number="OC999905", client_type="llp")
    filled, _ = services.import_company(owner(), client.company_number, client=client)
    assert filled.pk == client.pk
    client.refresh_from_db()
    assert client.name == "Our name for it"  # staff's name is kept
    roles = {link.contact.full_name: link.roles for link in client.client_contacts.all()}
    assert roles == {"Fiona Partner": ["member", "psc"], "George Memberson": ["member"]}


def test_a_new_company_with_no_accounts_filed():
    client, _ = services.import_company(owner(), "16999902")
    assert client.last_accounts_made_up_to is None
    assert client.last_statement_made_up_to is None
    assert client.next_accounts_due == date(2028, 4, 1)
    assert client.next_statement_due == date(2027, 7, 14)


def test_resigned_officers_and_former_owners_are_not_added():
    client, _ = services.import_company(owner(), "08999903")
    names = {link.contact.full_name for link in client.client_contacts.all()}
    assert names == {"Daniel Fresh"}
    assert not Contact.objects.filter(last_name="Leaver").exists()


def test_a_dissolved_company_is_stored_and_the_manager_is_told():
    boss = manager()
    client, _ = services.import_company(owner(), "07999904", manager=boss)
    assert client.company_status == "dissolved"
    assert client.next_statement_due is None and client.next_accounts_due is None
    assert Notification.objects.filter(user=boss, message__contains="dissolved").count() == 1
    # The next sync does not repeat the notice.
    services.sync_client(client, today=SUNDAY)
    assert Notification.objects.filter(user=boss).count() == 1


def test_a_sync_with_nothing_changed_writes_no_events(ch):
    client, _ = services.import_company(owner(), "09999901")
    before = ActivityEvent.objects.count()
    result = services.sync_client(client, today=SUNDAY)
    assert result.full and result.changes == []
    assert ActivityEvent.objects.count() == before


def test_a_weekday_sync_with_the_same_etag_fetches_only_the_profile(ch):
    client, _ = services.import_company(owner(), "09999901")
    ch.requests.clear()
    result = services.sync_client(client, today=TUESDAY)
    assert not result.full
    assert len(ch.requests) == 1 and ch.requests[0].endswith("/company/09999901")


def test_the_sync_writes_one_event_per_change(ch):
    boss = manager()
    client, _ = services.import_company(owner(), "08999903", manager=boss)
    profile = ch.load("08999903", "profile")
    profile = copy.deepcopy(profile)
    profile["etag"] = "changed"
    profile["company_status"] = "liquidation"
    profile["accounts"]["next_due"] = "2026-12-31"
    profile["registered_office_address"]["address_line_1"] = "2 Other Road"
    ch.set("/company/08999903", profile)
    officers = ch.load("08999903", "officers")
    officers["items"][0]["resigned_on"] = "2026-10-01"  # Daniel leaves
    officers["items"].append(
        {
            "name": "NEWCOMER, Iris",
            "officer_role": "director",
            "appointed_on": "2026-10-01",
            "date_of_birth": {"month": 5, "year": 1990},
            "links": {
                "self": "/company/08999903/appointments/NEW1",
                "officer": {"appointments": "/officers/NEW1OFF/appointments"},
            },
        }
    )
    ch.set("/company/08999903/officers", officers)
    owners = ch.load("08999903", "psc")
    owners["items"][0]["ceased_on"] = "2026-10-01"
    ch.set("/company/08999903/persons-with-significant-control", owners)
    filings = ch.load("08999903", "filings")
    filings["items"].insert(
        0,
        {
            "category": "officers",
            "type": "AP01",
            "date": "2026-10-02",
            "description": "appoint-person-director-company-with-name-date",
            "transaction_id": "TXNNEW",
        },
    )
    ch.set("/company/08999903/filing-history", filings)

    before = set(ch_events(client).values_list("pk", flat=True))
    result = services.sync_client(client, today=TUESDAY)
    new = ch_events(client).exclude(pk__in=before)
    verbs = sorted(new.values_list("verb", flat=True))
    assert verbs == [
        "companieshouse.address_changed",
        "companieshouse.date_changed",
        "companieshouse.filing",
        "companieshouse.officer_appointed",
        "companieshouse.officer_resigned",
        "companieshouse.owner_ceased",
        "companieshouse.status_changed",
    ]
    assert len(result.changes) == 7
    assert new.get(verb="companieshouse.date_changed").summary == (
        "Companies House: Next accounts due changed from 30/11/2026 to 31/12/2026."
    )
    # The resigned officer is marked, not deleted. The newcomer is added.
    daniel = client.client_contacts.get(contact__last_name="Fresh")
    assert daniel.resigned_on == date(2026, 10, 1)
    assert Contact.objects.filter(last_name="Fresh").exists()
    assert client.client_contacts.filter(contact__last_name="Newcomer").exists()
    # A non-active status notifies the manager.
    assert Notification.objects.filter(user=boss, message__contains="liquidation").exists()
    # And running it again changes nothing.
    assert services.sync_client(client, today=SUNDAY).changes == []


def test_a_resigned_officer_already_linked_is_marked_resigned_not_deleted():
    leaver = ContactFactory(
        first_name="Margaret", last_name="Leaver", birth_month=4, birth_year=1960
    )
    client = ClientFactory(company_number="08999903")
    ClientContact.objects.create(client=client, contact=leaver, roles=["director"])
    services.import_company(owner(), "08999903", client=client)
    link = client.client_contacts.get(contact=leaver)
    assert link.resigned_on == date(2025, 6, 30)
    assert Contact.objects.filter(pk=leaver.pk).exists()


def test_a_name_change_follows_only_if_the_client_kept_the_registered_name(ch):
    client, _ = services.import_company(owner(), "09999901")
    profile = copy.deepcopy(ch.load("09999901", "profile"))
    profile["company_name"] = "EXAMPLE RENAMED LTD"
    ch.set("/company/09999901", profile)
    services.sync_client(client, today=TUESDAY)
    client.refresh_from_db()
    assert client.name == "EXAMPLE RENAMED LTD"
    assert ch_events(client).filter(verb="companieshouse.name_changed").count() == 1


def test_the_nightly_job_syncs_live_clients_only(ch):
    synced, _ = services.import_company(owner(), "09999901")
    former = ClientFactory(company_number="16999902", status=Client.Status.FORMER)
    missing = ClientFactory(company_number="12345678")
    run = run_job("ch_sync")
    assert run.state == "done"
    assert run.counts == {"synced": 1, "changed": 0, "failed": 1}
    assert not CompanySnapshot.objects.filter(client=former).exists()
    assert not CompanySnapshot.objects.filter(client=missing).exists()
    assert "could not be synced" in run.message
    assert synced in jobs.clients_to_sync()


def test_the_nightly_job_fails_on_a_refused_key(ch, monkeypatch):
    from apps.companieshouse import api

    ClientFactory(company_number="09999901")
    boss = owner()

    def refuse(*args, **kwargs):
        raise api.AuthFailed(401)

    monkeypatch.setattr(services, "sync_client", refuse)
    run = run_job("ch_sync")
    assert run.state == "failed"
    assert "refused the API key" in run.message
    assert Notification.objects.filter(user=boss).exists()
