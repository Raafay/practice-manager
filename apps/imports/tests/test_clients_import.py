"""Clients import: reading, matching, checking, cleaning and saving. Spec 11, sections 2 and 4."""

import time
from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.clients.models import Client, Note
from apps.clients.tests.factories import ClientFactory
from apps.imports import services
from apps.imports.models import ImportedRecord, ImportRun, SavedMatching
from apps.imports.tests.helpers import boss, csv_bytes, imported, ready, sam, upload

pytestmark = pytest.mark.django_db


def test_headings_are_matched_from_their_text():
    run = upload(boss(), "clients", "clients_clean.csv")
    assert run.mapping == {
        "Client Code": "reference",
        "Client Name": "name",
        "Client Type": "client_type",
        "Company Number": "company_number",
        "Year End": "year_end",
        "Manager": "manager",
        "Email": "email",
        "Telephone": "phone",
        "Address Line 1": "address_1",
        "Town": "address_3",
        "Postcode": "postcode",
        "VAT Number": "vat_number",
        "VAT Quarter": "vat_stagger",
        "UTR": "utr",
        "Client Since": "client_since",
        "Source": "source",
        "Tags": "tags",
        "Notes": "notes",
    }
    assert run.row_count == 4 and run.encoding == "UTF-8" and run.delimiter == ","


def test_the_messy_file_gives_the_right_counts_and_messages():
    actor = boss()
    run = ready(actor, "clients", "clients_messy.csv")
    assert run.encoding == "UTF-8 (with BOM)" and run.delimiter == ";"
    assert run.headers[0] == "Ref"  # the byte order mark is not part of the heading
    result = services.check(run)
    assert result.counts == {"create": 3, "update": 0, "problems": 3}
    problems = {r.number: r.problems for r in result.failed}
    assert problems == {
        4: ["Same client as row 2 (the same name). Remove one of the two rows."],
        5: ["Type: “Company of some kind” is not a client type we know."],
        6: ["Client since: “31/02/2020” is not a date. Use dd/mm/yyyy or yyyy-mm-dd."],
    }
    assert Client.objects.count() == 0  # the check saves nothing


def test_company_numbers_are_padded_and_both_date_formats_are_read():
    actor = boss()
    run = imported(actor, "clients", "clients_messy.csv")
    hazel = Client.objects.get(reference="M001")
    assert hazel.name == "Hazel Example Ltd"  # spaces trimmed
    assert hazel.company_number == "00001234"
    assert hazel.client_since == date(2020, 2, 1)
    ivy = Client.objects.get(reference="M002")
    assert ivy.client_since == date(2021, 3, 31)
    assert ivy.status == "active"  # "live" is a common spelling of active
    assert (ivy.accounting_ref_day, ivy.accounting_ref_month) == (30, 9)
    assert Client.objects.get(reference="M006").client_type == "ltd"
    assert run.counts == {"created": 3, "updated": 0, "failed": 3}


def test_a_failed_row_does_not_stop_the_good_rows_and_is_offered_as_csv():
    run = imported(boss(), "clients", "clients_messy.csv")
    assert set(Client.objects.values_list("reference", flat=True)) == {"M001", "M002", "M006"}
    rows = services.failure_rows(run)
    assert [r["row"] for r in rows] == [4, 5, 6]
    assert run.data == ""  # the file itself is not kept


def test_the_clean_file_fills_every_field():
    actor = boss()
    manager = sam()
    run = imported(actor, "clients", "clients_clean.csv")
    assert run.counts == {"created": 4, "updated": 0, "failed": 0}
    juniper = Client.objects.get(reference="X001")
    assert juniper.client_type == "ltd" and juniper.company_number == "09999901"
    assert juniper.manager == manager
    assert juniper.vat_stagger == 1 and juniper.company_utr == "1111111111"
    assert juniper.correspondence_address == "1 Sample Street\nTestville\nZZ1 1ZZ"
    assert juniper.source == "word_of_mouth"
    assert sorted(t.name for t in juniper.tags.all()) == ["Bookkeeping", "Payroll"]
    assert Note.objects.get(client=juniper).text == "Moved from the old system."
    quillon = Client.objects.get(reference="X002")
    assert quillon.client_type == "llp" and quillon.manager == manager  # found by email
    teasel = Client.objects.get(reference="X004")
    assert (teasel.accounting_ref_day, teasel.accounting_ref_month) == (31, 12)
    assert teasel.vat_stagger == 2


def test_imported_clients_are_active_with_no_checklist_and_aml_needs_review():
    from apps.aml.services import state_of

    imported(boss(), "clients", "clients_clean.csv")
    client = Client.objects.get(reference="X001")
    assert client.status == "active"
    assert not client.onboarding_items.exists()
    assert state_of(client)[0] == "needs_review"


def test_every_created_record_is_tagged_with_its_run_and_the_run_is_logged():
    from apps.events.models import ActivityEvent

    run = imported(boss(), "clients", "clients_clean.csv")
    assert ImportedRecord.objects.filter(run=run, model="client").count() == 4
    assert ActivityEvent.objects.filter(verb="import.run").count() == 1
    assert ActivityEvent.objects.filter(verb="import.client_created").count() == 4


def test_a_match_fills_only_empty_fields_unless_overwrite_is_ticked():
    actor = boss()
    existing = ClientFactory(
        name="Juniper Example Trading Ltd", reference="X001", email="", phone="01632 960999"
    )
    run = imported(actor, "clients", "clients_clean.csv")
    assert run.counts["created"] == 3 and run.counts["updated"] == 1
    existing.refresh_from_db()
    assert existing.email == "office@juniper.example.com"  # was empty
    assert existing.phone == "01632 960999"  # kept

    imported(actor, "clients", "clients_clean.csv", overwrite=True)
    existing.refresh_from_db()
    assert existing.phone == "01632 960001"


def test_matching_by_company_number_then_name_without_case():
    actor = boss()
    by_number = ClientFactory(name="Another Name Ltd", company_number="09999901")
    by_name = ClientFactory(name="ROWAN EXAMPLE (SOLE TRADER)", client_type="sole_trader")
    result = services.check(ready(actor, "clients", "clients_clean.csv"))
    targets = {r.number: r.target_id for r in result.rows}
    assert targets[2] == by_number.pk and targets[4] == by_name.pk


def test_unknown_manager_and_missing_type_are_problems():
    raw = csv_bytes("Name,Type,Manager", "Example One Ltd,Ltd,Nobody Here", "Example Two Ltd,,")
    result = services.check(ready(boss(), "clients", "x.csv", raw))
    assert result.failed[0].problems == ["Manager: nobody on the team matches “Nobody Here”."]
    assert result.failed[1].problems == ["Type: needed for a new client."]


def test_a_utr_is_never_written_into_the_failures_file():
    raw = csv_bytes("Name,Type,UTR", "Example One Ltd,Mystery,1111111111")
    run = imported(boss(), "clients", "x.csv", raw)
    row = services.failure_rows(run)[0]
    assert row["values"] == ["Example One Ltd", "Mystery", "(left out)"]
    assert "1111111111" not in run.failures


def test_a_saved_matching_is_offered_when_the_same_headings_appear_again():
    actor = boss()
    first = upload(actor, "clients", "clients_clean.csv")
    mapping = {**first.mapping, "Notes": ""}
    services.set_mapping(actor, first, mapping, overwrite=False, save_as="Old system clients")
    saved = SavedMatching.objects.get(name="Old system clients")
    again = upload(actor, "clients", "clients_clean.csv")
    assert again.matching == saved
    assert again.mapping["Notes"] == ""  # the saved choice, not the suggestion
    other = upload(actor, "clients", "clients_messy.csv")
    assert other.matching is None


def test_mapping_problems_are_refused():
    actor = boss()
    run = upload(actor, "clients", "clients_clean.csv")
    twice = {**run.mapping, "Town": "name"}
    with pytest.raises(Exception, match="more than one column"):
        services.set_mapping(actor, run, twice, overwrite=False)
    with pytest.raises(Exception, match="Name"):
        services.set_mapping(actor, run, {**run.mapping, "Client Name": ""}, overwrite=False)


def test_an_import_of_500_rows_is_quick_and_uses_bulk_writes():
    lines = ["Client Code,Client Name,Client Type,Company Number,Client Since,Tags,Notes"]
    for i in range(500):
        lines.append(f"B{i:04d},Bulk Example {i} Ltd,Ltd,{i + 1},01/04/2020,Imported,Note {i}")
    actor = boss()
    run = ready(actor, "clients", "bulk.csv", csv_bytes(*lines))
    started = time.monotonic()
    with CaptureQueriesContext(connection) as queries:
        run = services.run_import(actor, run)
    assert run.counts == {"created": 500, "updated": 0, "failed": 0}
    assert len(queries) < 60, len(queries)
    assert time.monotonic() - started < 20
    assert Client.objects.get(reference="B0499").company_number == "00000500"


def test_automatic_references_follow_on_from_the_highest():
    ClientFactory(reference="C0041")
    raw = csv_bytes("Name,Type", "Example One Ltd,Ltd", "Example Two Ltd,Ltd")
    imported(boss(), "clients", "x.csv", raw)
    assert set(Client.objects.values_list("reference", flat=True)) == {"C0041", "C0042", "C0043"}


def test_an_existing_clients_status_is_not_changed():
    ClientFactory(name="Example One Ltd", status="paused")
    raw = csv_bytes("Name,Type,Status", "Example One Ltd,Ltd,Active")
    run = ready(boss(), "clients", "x.csv", raw)
    result = services.check(run)
    assert "not changed by an import" in result.rows[0].warnings[0]
    services.run_import(boss(), run)
    assert Client.objects.get(name="Example One Ltd").status == "paused"


def test_a_file_cannot_be_imported_twice():
    actor = boss()
    run = imported(actor, "clients", "clients_clean.csv")
    with pytest.raises(Exception, match="already been imported"):
        services.run_import(actor, run)
    assert ImportRun.objects.get(pk=run.pk).state == "done"
