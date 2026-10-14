"""Contacts and services imports, the migration helper and Companies House fetch."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.clients.models import Client, ClientContact, Contact
from apps.clients.tests.factories import ClientContactFactory, ContactFactory
from apps.imports import helper, services
from apps.imports.jobs import fetch_run, import_fetch
from apps.imports.models import ImportRun
from apps.imports.tests.helpers import boss, csv_bytes, imported, ready
from apps.services.models import ClientService, Deadline, FeeChange
from apps.services.tests.factories import take

pytestmark = pytest.mark.django_db


@pytest.fixture
def clients():
    imported(boss(), "clients", "clients_clean.csv")
    return {c.reference: c for c in Client.objects.all()}


def test_contacts_file_counts_and_messages(clients):
    result = services.check(ready(boss(), "contacts", "contacts.csv"))
    assert result.counts == {"create": 4, "update": 0, "problems": 2}
    problems = {r.number: r.problems for r in result.failed}
    assert problems == {
        6: ["Client: no client matches “X009”."],
        7: ["Role: “Wizard” is not a role we know."],
    }


def test_contacts_are_created_and_linked_with_roles_and_flags(clients):
    run = imported(boss(), "contacts", "contacts.csv")
    assert run.counts == {"created": 4, "updated": 0, "failed": 2}
    alex = Contact.objects.get(email="alex@juniper.example.com")
    assert alex.date_of_birth == date(1980, 2, 1) and alex.title == "Ms"
    link = ClientContact.objects.get(contact=alex)
    assert link.client == clients["X001"] and link.is_main and link.roles == ["director"]
    blake = ClientContact.objects.get(contact__first_name="Blake")
    assert blake.roles == ["director", "shareholder"] and not blake.is_main
    casey = ClientContact.objects.get(contact__first_name="Casey")
    assert casey.client == clients["X002"]  # found by name
    assert casey.roles == ["member"] and casey.contact.date_of_birth == date(1975, 6, 30)


def test_a_contact_matches_by_email_then_by_name_within_the_client(clients):
    by_email = ContactFactory(
        first_name="Alexandra", last_name="Other", email="alex@juniper.example.com"
    )
    by_name = ContactFactory(first_name="Blake", last_name="Sampleton", email="")
    ClientContactFactory(client=clients["X001"], contact=by_name, is_main=True)
    result = services.check(ready(boss(), "contacts", "contacts.csv"))
    targets = {r.number: r.target_id for r in result.rows}
    assert targets[2] == by_email.pk and targets[3] == by_name.pk
    # X001 already has a main contact, so Alex is added without it.
    assert "already has a main contact" in result.rows[0].warnings[0]
    services.run_import(boss(), ready(boss(), "contacts", "contacts.csv"))
    by_name.refresh_from_db()
    assert by_name.email == "blake@juniper.example.com"  # was empty
    assert ClientContact.objects.get(client=clients["X001"], is_main=True).contact == by_name


def test_services_file_counts_and_messages(clients):
    result = services.check(ready(boss(), "services", "services.csv"))
    assert result.counts == {"create": 4, "update": 0, "problems": 2}
    problems = {r.number: r.problems for r in result.failed}
    assert problems == {
        6: ["Service: Accounts does not apply to a sole trader."],
        7: [
            "Service: “Gardening” is not one of the practice's services. "
            "Check the name in Settings, Services."
        ],
    }


def test_services_are_created_with_fees_and_deadlines(clients):
    # Filing dates as Companies House would give them, so the accounts rule has its dates.
    Client.objects.filter(reference="X001").update(
        next_accounts_made_up_to=date(2026, 3, 31), next_accounts_due=date(2026, 12, 31)
    )
    run = imported(boss(), "services", "services.csv")
    assert run.counts == {"created": 4, "updated": 0, "failed": 2}
    accounts = ClientService.objects.get(client=clients["X001"], service__code="accounts")
    assert accounts.fee_amount == Decimal("1200.00") and accounts.fee_frequency == "annual"
    assert accounts.starts_on == date(2019, 4, 1) and accounts.state == "active"
    assert FeeChange.objects.filter(client_service=accounts).count() == 1
    sa = ClientService.objects.get(client=clients["X003"], service__code="self_assessment")
    assert sa.fee_amount == Decimal("250.00") and sa.fee_frequency == "annual"
    assert Deadline.objects.filter(client=clients["X001"]).exists()


def test_a_fee_needs_fees_view(clients):
    from apps.pipeline.tests.helpers import no_fee_staff

    actor = no_fee_staff()
    actor.extra_rights = ["data.import"]
    actor.save()
    raw = csv_bytes("Client,Service,Fee", "X001,Accounts,10")
    run = services.start_run(actor, "services", "s.csv", raw)
    with pytest.raises(Exception, match="cannot see fees"):
        services.set_mapping(actor, run, run.mapping, overwrite=False)


def test_an_existing_service_gets_its_empty_fee_filled(clients):
    cs = take(clients["X001"], "accounts", fee_amount=None)
    run = imported(boss(), "services", "services.csv")
    assert run.counts["updated"] == 1
    cs.refresh_from_db()
    assert cs.fee_amount == Decimal("1200.00")


# ---------------------------------------------------------------- undo


def test_undo_removes_untouched_records_and_keeps_changed_ones(clients):
    from apps.clients import services as client_services

    actor = boss()
    run = ImportRun.objects.get(kind="clients")
    changed = clients["X002"]
    changed.phone = "01632 960555"
    changed.save()
    noted = clients["X003"]
    client_services.add_note(actor, noted, "Phoned about the move.")
    run = services.undo(actor, run)
    assert set(Client.objects.values_list("reference", flat=True)) == {"X002", "X003"}
    assert {k["label"] for k in run.undo_report} == {
        "Quillon Example Partners LLP (X002)",
        "Rowan Example (Sole Trader) (X003)",
    }
    assert run.state == "undone" and run.counts["removed"] == 2 and run.counts["kept"] == 2


def test_undo_of_contacts_and_services_leaves_the_clients(clients):
    actor = boss()
    Client.objects.filter(reference="X001").update(
        next_accounts_made_up_to=date(2026, 3, 31), next_accounts_due=date(2026, 12, 31)
    )
    contacts = imported(actor, "contacts", "contacts.csv")
    work = imported(actor, "services", "services.csv")
    assert Deadline.objects.exists()
    alex = Contact.objects.get(first_name="Alex")
    alex.mobile = "07700 900999"
    alex.save()
    services.undo(actor, work)
    assert not ClientService.objects.exists()
    assert not Deadline.objects.exists()
    contacts = services.undo(actor, contacts)
    assert list(Contact.objects.values_list("first_name", flat=True)) == ["Alex"]
    assert Client.objects.count() == 4
    assert contacts.undo_report == [
        {"label": "Alex Sampleton", "reason": "Their details have changed since."}
    ]


def test_a_service_whose_deadline_was_marked_is_kept(clients):
    Client.objects.filter(reference="X001").update(
        next_accounts_made_up_to=date(2026, 3, 31), next_accounts_due=date(2026, 12, 31)
    )
    actor = boss()
    work = imported(actor, "services", "services.csv")
    deadline = Deadline.objects.filter(client=clients["X001"]).first()
    from apps.services import deadlines

    deadlines.mark_done(actor, deadline)
    work = services.undo(actor, work)
    assert ClientService.objects.filter(pk=deadline.client_service_id).exists()
    assert any("deadlines have been marked" in k["reason"] for k in work.undo_report)


# ---------------------------------------------------------------- migration helper


def test_the_helper_marks_only_what_was_ticked():
    from apps.clients.tests.factories import ClientFactory

    actor = boss()
    client = ClientFactory(status="active")
    today = timezone.localdate()
    rows = [
        Deadline.objects.create(
            client=client,
            rule="vat_return",
            period_key=str(i),
            label=f"Period {i}",
            due_date=today + timedelta(days=d),
            original_due_date=today + timedelta(days=d),
        )
        for i, d in enumerate((-40, -5, 10, 45))
    ]
    listed = [d.pk for _title, items in helper.groups() for d in items]
    assert listed == [rows[0].pk, rows[1].pk, rows[2].pk]  # not the one due in 45 days
    count = helper.mark_already_done(
        actor, [rows[0].pk, rows[2].pk, rows[3].pk], complete_tasks=True
    )
    assert count == 2  # the 45-day one is not listed, so it cannot be marked
    states = dict(Deadline.objects.values_list("pk", "status"))
    assert states == {
        rows[0].pk: "done",
        rows[1].pk: "open",
        rows[2].pk: "done",
        rows[3].pk: "open",
    }
    assert Deadline.objects.get(pk=rows[0].pk).done_note == helper.DONE_NOTE


# ---------------------------------------------------------------- Companies House


def test_fetch_from_companies_house_runs_in_the_background_with_progress(clients):
    from apps.jobs.models import JobLock

    actor = boss()
    run = ImportRun.objects.get(kind="clients")
    services.request_fetch(actor, run)
    run.refresh_from_db()
    assert run.fetch_state == "waiting" and run.fetch_total == 3
    assert JobLock.objects.get(name="import_fetch").requested_at is not None
    counts = import_fetch(None)
    run.refresh_from_db()
    assert counts["runs"] == 1
    assert run.fetch_state == "done" and run.fetch_done == 3 and run.fetch_failed == 0
    juniper = Client.objects.get(reference="X001")
    assert juniper.last_synced_at is not None
    # The fetch is the system's own change, so undo still removes the client.
    assert Contact.objects.exists()  # officers and owners came across
    run.refresh_from_db()
    run = services.undo(actor, run)
    assert run.undo_report == []
    assert not Client.objects.exists()
    assert not Contact.objects.exists()  # nobody is left behind without a client


def test_a_company_not_found_counts_as_failed_and_the_rest_carry_on(clients):
    Client.objects.filter(reference="X001").update(company_number="01234567")
    run = ImportRun.objects.get(kind="clients")
    services.request_fetch(boss(), run)
    run.refresh_from_db()
    fetch_run(run)
    run.refresh_from_db()
    assert (run.fetch_done, run.fetch_failed, run.fetch_state) == (2, 1, "done")


def test_fetch_needs_a_clients_run_with_company_numbers():
    raw = csv_bytes("Name,Type", "Example One,Individual")
    run = imported(boss(), "clients", "x.csv", raw)
    with pytest.raises(Exception, match="company number"):
        services.request_fetch(boss(), run)
