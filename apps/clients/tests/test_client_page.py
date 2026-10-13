import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients.models import Client, CustomFieldDefinition
from apps.events.models import ActivityEvent

from .factories import ClientContactFactory, ClientFactory, NoteFactory, TagFactory

pytestmark = pytest.mark.django_db


def panel_titles(response):
    return [item["panel"].title for item in response.context["panels"]]


def test_new_client_gets_a_reference_and_an_event(client):
    boss = owner()
    sign_in(client, boss)
    response = client.post(
        reverse("clients:new"),
        {
            "name": "Fresh Start Ltd",
            "client_type": "ltd",
            "manager": boss.pk,
            "first_name": "Ada",
            "last_name": "Sample",
            "email": "ada@example.com",
        },
    )
    created = Client.objects.get(name="Fresh Start Ltd")
    assert response["Location"] == reverse("clients:detail", args=[created.pk])
    assert created.reference == "C0001"
    assert created.manager == boss
    assert created.main_contact.full_name == "Ada Sample"
    event = ActivityEvent.objects.get(verb="client.created")
    assert event.client == created and "Fresh Start Ltd" in event.summary


def test_references_count_up_and_can_be_edited(client):
    first, second = ClientFactory(), ClientFactory()
    assert (first.reference, second.reference) == ("C0001", "C0002")
    first.reference = "OLD-7"
    first.save()
    assert ClientFactory().reference == "C0003"


def test_new_client_form_links_an_existing_person_by_email(client):
    from apps.clients.models import Contact

    existing = ClientContactFactory(
        contact__email="shared@example.com", contact__first_name="Sam", contact__last_name="Shared"
    ).contact
    sign_in(client, staff())
    client.post(
        reverse("clients:new"),
        {
            "name": "Second Co",
            "client_type": "ltd",
            "first_name": "Samuel",
            "last_name": "Shared",
            "email": "SHARED@example.com",
        },
    )
    assert Contact.objects.count() == 1
    assert Client.objects.get(name="Second Co").main_contact == existing


def test_new_client_needs_both_contact_names_or_neither(client):
    sign_in(client, staff())
    response = client.post(
        reverse("clients:new"), {"name": "X", "client_type": "ltd", "first_name": "Only"}
    )
    assert response.status_code == 422
    assert not Client.objects.exists()


def test_panels_follow_the_client_type(client):
    sign_in(client, staff())
    company = ClientFactory(client_type="ltd")
    sole = ClientFactory(client_type="sole_trader")
    assert "Company details" in panel_titles(
        client.get(reverse("clients:detail", args=[company.pk]))
    )
    page = client.get(reverse("clients:detail", args=[sole.pk]))
    assert "Company details" not in panel_titles(page)
    assert client.get(reverse("clients:panel", args=[sole.pk, "company"])).status_code == 404
    assert client.get(reverse("clients:panel_edit", args=[sole.pk, "company"])).status_code == 404
    # Making Tax Digital fields are for individuals and sole traders only.
    assert (
        b"Making tax digital" in client.get(reverse("clients:panel", args=[sole.pk, "tax"])).content
    )
    assert (
        b"Making tax digital"
        not in client.get(reverse("clients:panel", args=[company.pk, "tax"])).content
    )


def test_editing_a_panel_in_place_saves_and_logs_what_changed(client):
    target = ClientFactory(name="Old Name Ltd", phone="")
    person = staff()
    sign_in(client, person)
    form = client.get(reverse("clients:panel_edit", args=[target.pk, "contact"]))
    assert b"<form" in form.content
    response = client.post(
        reverse("clients:panel_edit", args=[target.pk, "contact"]),
        {
            "email": "hello@example.com",
            "phone": "01632 960001",
            "website": "",
            "correspondence_address": "",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.phone == "01632 960001"
    event = ActivityEvent.objects.get(verb="client.changed")
    assert event.client == target
    assert "Email" in event.summary and "Phone" in event.summary
    assert event.data["fields"]["phone"] == {"old": "", "new": "01632 960001"}


def test_a_panel_with_errors_is_redisplayed(client):
    target = ClientFactory()
    sign_in(client, staff())
    response = client.post(
        reverse("clients:panel_edit", args=[target.pk, "contact"]),
        {"email": "not-an-email", "phone": "", "website": "", "correspondence_address": ""},
    )
    assert response.status_code == 422
    target.refresh_from_db()
    assert target.email == ""


def test_duplicate_reference_is_refused(client):
    ClientFactory(reference="DUP-1")
    target = ClientFactory()
    sign_in(client, staff())
    response = client.post(
        reverse("clients:panel_edit", args=[target.pk, "required"]),
        {
            "name": target.name,
            "client_type": "ltd",
            "reference": "DUP-1",
            "partner": "",
            "manager": "",
            "team": "",
        },
    )
    assert response.status_code == 422


def test_encrypted_fields_are_masked_and_show_is_logged(client):
    target = ClientFactory(client_type="ltd", company_utr="1234567890", ch_auth_code="AB12CD")
    viewer = staff()
    sign_in(client, viewer)
    page = client.get(reverse("clients:panel", args=[target.pk, "tax"])).content.decode()
    assert "1234567890" not in page and "••••••890" in page
    company = client.get(reverse("clients:panel", args=[target.pk, "company"])).content.decode()
    assert "AB12CD" not in company
    whole = client.get(reverse("clients:detail", args=[target.pk])).content.decode()
    assert "1234567890" not in whole and "AB12CD" not in whole
    assert not ActivityEvent.objects.filter(verb="sensitive.revealed").exists()

    revealed = client.post(reverse("clients:client_reveal", args=[target.pk, "company_utr"]))
    assert b"1234567890" in revealed.content
    assert revealed["Cache-Control"] == "no-store"
    event = ActivityEvent.objects.get(verb="sensitive.revealed")
    assert event.client == target and event.actor == viewer
    assert "1234567890" not in str(event.data) and "1234567890" not in event.summary


def test_only_listed_secret_fields_can_be_revealed(client):
    target = ClientFactory(name="Secretive Ltd")
    sign_in(client, owner())
    assert (
        client.post(reverse("clients:client_reveal", args=[target.pk, "name"])).status_code == 403
    )
    assert (
        client.post(reverse("clients:client_reveal", args=[target.pk, "reference"])).status_code
        == 403
    )


def test_saving_an_encrypted_field_never_logs_its_value(client):
    target = ClientFactory(client_type="ltd")
    sign_in(client, staff())
    post = {
        "vat_number": "",
        "company_utr": "1234567890",
        "cis_role": "none",
        "vat_registered_on": "",
        "vat_frequency": "",
        "vat_stagger": "",
        "vat_scheme": "",
        "vat_year_end_month": "",
        "paye_reference": "",
        "accounts_office_reference": "",
        "payroll_frequency": "",
        "pay_day_rule": "",
        "pay_day": "",
        "first_pay_date": "",
        "employee_count": "",
        "pension_provider": "",
        "auto_enrolment_start": "",
        "last_reenrolment": "",
    }
    response = client.post(reverse("clients:panel_edit", args=[target.pk, "tax"]), post)
    assert response.status_code == 200
    target.refresh_from_db()
    assert target.company_utr == "1234567890"
    for event in ActivityEvent.objects.all():
        assert "1234567890" not in str(event.data) and "1234567890" not in event.summary
    # Blank keeps the saved value; the tick box removes it.
    client.post(reverse("clients:panel_edit", args=[target.pk, "tax"]), {**post, "company_utr": ""})
    target.refresh_from_db()
    assert target.company_utr == "1234567890"
    client.post(
        reverse("clients:panel_edit", args=[target.pk, "tax"]), {**post, "clear_company_utr": "on"}
    )
    target.refresh_from_db()
    assert target.company_utr == ""


def test_utr_must_be_ten_digits(client):
    target = ClientFactory(client_type="ltd")
    sign_in(client, staff())
    response = client.post(
        reverse("clients:panel_edit", args=[target.pk, "tax"]),
        {"company_utr": "123", "cis_role": "none"},
    )
    assert response.status_code == 422


def test_companies_house_dates_are_read_only_once_a_company_number_is_set(client):
    from datetime import date

    target = ClientFactory(
        client_type="ltd", company_number="ZZ000001", next_accounts_due=date(2027, 1, 31)
    )
    sign_in(client, staff())
    form = client.get(reverse("clients:panel_edit", args=[target.pk, "company"])).context["form"]
    assert form.fields["next_accounts_due"].disabled
    client.post(
        reverse("clients:panel_edit", args=[target.pk, "company"]),
        {
            "company_number": "ZZ000001",
            "next_accounts_due": "2030-01-01",
            "trading_name": "Changed",
        },
    )
    target.refresh_from_db()
    assert target.next_accounts_due == date(2027, 1, 31) and target.trading_name == "Changed"
    free = ClientFactory(client_type="ltd")
    assert (
        not client.get(reverse("clients:panel_edit", args=[free.pk, "company"]))
        .context["form"]
        .fields["next_accounts_due"]
        .disabled
    )


def test_tags_and_custom_fields_are_edited_in_the_internal_panel(client):
    tag = TagFactory(name="VIP")
    definition = CustomFieldDefinition.objects.create(name="Software", kind="text")
    yes_no = CustomFieldDefinition.objects.create(name="Dormant", kind="yes_no")
    target = ClientFactory()
    sign_in(client, staff())
    response = client.post(
        reverse("clients:panel_edit", args=[target.pk, "internal"]),
        {
            "tags": [tag.pk],
            f"cf_{definition.pk}": "Xero",
            f"cf_{yes_no.pk}": "yes",
            "source": "website",
            "client_since": "2020-04-06",
            "payment_method": "direct_debit",
        },
    )
    assert response.status_code == 200
    target.refresh_from_db()
    assert list(target.tags.all()) == [tag]
    assert target.custom_values == {str(definition.pk): "Xero", str(yes_no.pk): "yes"}
    page = client.get(reverse("clients:panel", args=[target.pk, "internal"])).content.decode()
    assert "Xero" in page and "06/04/2020" in page and "VIP" in page


def test_tabs_load_as_partials_for_htmx_and_full_pages_otherwise(client):
    target = ClientFactory()
    sign_in(client, staff())
    url = reverse("clients:contacts", args=[target.pk])
    assert b"<html" in client.get(url).content
    partial = client.get(url, HTTP_HX_REQUEST="true")
    assert b"<html" not in partial.content and b'aria-label="Client sections"' in partial.content
    assert "HX-Request" in partial["Vary"]
    restore = client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_HISTORY_RESTORE_REQUEST="true")
    assert b"<html" in restore.content


def test_no_main_contact_shows_a_warning(client):
    target = ClientFactory()
    sign_in(client, staff())
    assert b"has no main contact" in client.get(reverse("clients:detail", args=[target.pk])).content
    ClientContactFactory(client=target, is_main=True)
    assert (
        b"has no main contact"
        not in client.get(reverse("clients:detail", args=[target.pk])).content
    )


def test_pinned_notes_show_on_the_info_tab(client):
    target = ClientFactory()
    NoteFactory(client=target, text="Pinned: call before the 5th", pinned=True)
    NoteFactory(client=target, text="Not pinned note")
    sign_in(client, staff())
    page = client.get(reverse("clients:detail", args=[target.pk])).content.decode()
    assert "Pinned: call before the 5th" in page and "Not pinned note" not in page


def test_notes_and_calls_appear_on_the_timeline_and_can_be_pinned(client):
    target = ClientFactory()
    person = staff()
    sign_in(client, person)
    assert client.get(reverse("clients:add_note", args=[target.pk])).status_code == 200
    client.post(
        reverse("clients:add_note", args=[target.pk]),
        {"text": "Agreed new year end", "pinned": "on"},
    )
    client.post(reverse("clients:log_call", args=[target.pk]), {"text": "Rang about VAT"})
    assert (
        client.post(reverse("clients:add_note", args=[target.pk]), {"text": "  "}).status_code
        == 422
    )
    timeline = client.get(reverse("clients:timeline", args=[target.pk])).content.decode()
    assert "Agreed new year end" in timeline and "Rang about VAT" in timeline
    assert "logged a call" in timeline
    note = target.notes.get(kind="note")
    assert note.pinned and note.author == person
    client.post(reverse("clients:pin_note", args=[target.pk, note.pk]))
    note.refresh_from_db()
    assert not note.pinned
    # The type filter narrows the timeline.
    only_calls = client.get(
        reverse("clients:timeline", args=[target.pk]), {"type": "call"}
    ).content.decode()
    assert "Rang about VAT" in only_calls and "Agreed new year end" not in only_calls


def test_pin_redirect_will_not_leave_the_site(client):
    target = ClientFactory()
    note = NoteFactory(client=target)
    sign_in(client, staff())
    response = client.post(
        reverse("clients:pin_note", args=[target.pk, note.pk]), {"next": "https://evil.example/"}
    )
    assert response["Location"] == reverse("clients:detail", args=[target.pk])


def test_a_note_belonging_to_another_client_is_not_found(client):
    one, two = ClientFactory(), ClientFactory()
    note = NoteFactory(client=two)
    sign_in(client, staff())
    assert client.post(reverse("clients:pin_note", args=[one.pk, note.pk])).status_code == 404


def test_company_number_links_to_companies_house(client):
    target = ClientFactory(company_number="ZZ000042")
    sign_in(client, staff())
    page = client.get(reverse("clients:detail", args=[target.pk])).content.decode()
    assert "company-information.service.gov.uk/company/ZZ000042" in page
    assert manager and owner  # keep factories imported for later tests
