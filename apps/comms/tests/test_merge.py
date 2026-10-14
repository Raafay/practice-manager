from datetime import date

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import staff
from apps.comms import merge
from apps.comms.services import build_context
from apps.companieshouse.models import CompanySnapshot

from .factories import client_with_contact, make_deadline

pytestmark = pytest.mark.django_db


def ctx_for(**extra):
    client, contact = client_with_contact(name="Acme Ltd", company_number="09999901")
    user = staff(name="Sam Writer", job_title="Accountant", email_signature="Sam\n01234 567890")
    deadline = make_deadline(client)
    return build_context(client, user=user, contact=contact, deadline=deadline)


def test_every_listed_field_is_known_and_renders_without_error():
    ctx = ctx_for()
    for name in merge.FIELDS:
        result = merge.render("{{ " + name + " }}", ctx)
        assert not result.unknown, name


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("client.name", "Acme Ltd"),
        ("client.company_number", "09999901"),
        ("contact.first_name", "Pat"),
        ("contact.last_name", "Sample"),
        ("contact.full_name", "Pat Sample"),
        ("user.name", "Sam Writer"),
        ("user.first_name", "Sam"),
        ("user.job_title", "Accountant"),
        ("deadline.label", "VAT return"),
        ("deadline.due_date", "07/11/2026"),
        ("deadline.period_end", "30/09/2026"),
    ],
)
def test_fields_give_their_values(field, expected):
    assert merge.render("{{ " + field + " }}", ctx_for()).text == expected


def test_practice_and_today_and_signature():
    from apps.core.models import PracticeSettings

    practice = PracticeSettings.load()
    practice.practice_name = "Sample Accountants"
    practice.phone = "01234 000000"
    practice.save()
    ctx = ctx_for()
    assert merge.render("{{ practice.name }} {{ practice.phone }}", ctx).text == (
        "Sample Accountants 01234 000000"
    )
    assert merge.render("{{ today }}", ctx).text == timezone.localdate().strftime("%d/%m/%Y")
    assert "01234 567890" in merge.render("{{ user.signature }}", ctx).text


def test_task_fields():
    from apps.tasks.tests.factories import make_task

    client, contact = client_with_contact()
    task = make_task(None, title="Prepare accounts", client=client, target_date=date(2026, 12, 1))
    ctx = build_context(client, task=task)
    assert merge.render("{{ task.title }} {{ task.target_date }}", ctx).text == (
        "Prepare accounts 01/12/2026"
    )


def test_money_and_services_blocks():
    from apps.services.tests.factories import take

    client, contact = client_with_contact()
    take(client, "accounts", fee_amount=100, fee_frequency="monthly")
    result = merge.render(
        "{{ services_list }}|{{ monthly_fee }}|{{ setup_fee }}", build_context(client)
    )
    assert "Accounts" in result.html
    assert "£100.00" in result.text


def test_unknown_field_is_flagged_and_blocks():
    result = merge.render("<p>Hi {{ client.nmae }}</p>", ctx_for())
    assert result.unknown == ["client.nmae"]
    assert result.blocked
    assert "merge-unknown" in result.html


def test_no_template_tags_are_executed():
    result = merge.render(
        "<p>{% load x %}{{ 7*7 }}{% if True %}yes{% endif %} {{ client.name }}</p>", ctx_for()
    )
    assert "{% if True %}yes{% endif %}" in result.html
    assert "49" not in result.html
    assert "Acme Ltd" in result.html


def test_values_are_escaped():
    client, contact = client_with_contact(name="<script>alert(1)</script> Ltd")
    result = merge.render("{{ client.name }}", build_context(client))
    assert "<script>" not in result.html


def test_link_fields_show_a_labelled_placeholder_and_block():
    # portal_link has a builder since Stage 10; proposal_link is filled in only when sending one.
    result = merge.render("{{ proposal_link }}", ctx_for())
    assert result.placeholders == ["proposal_link"]
    assert result.blocked
    assert "not available yet" in result.text


def test_link_fields_render_a_button_when_a_builder_exists(monkeypatch):
    monkeypatch.setitem(
        merge.LINK_BUILDERS, "portal_link", lambda client, ctx: "https://example.com/p/1"
    )
    result = merge.render("{{ portal_link }}", ctx_for())
    assert not result.blocked
    assert 'href="https://example.com/p/1"' in result.html
    assert "https://example.com/p/1" in result.text


def test_cs01_block_lists_what_companies_house_holds_and_asks_about_shareholders():
    client, contact = client_with_contact()
    CompanySnapshot.objects.create(
        client=client,
        company_number="09999901",
        synced_at=timezone.now(),
        profile={
            "registered_office_address": {
                "address_line_1": "1 Example Street",
                "postal_code": "ZZ1 1ZZ",
            },
            "sic_codes": ["62020"],
            "confirmation_statement": {"next_made_up_to": "2027-06-30"},
        },
        officers=[
            {"name": "NEWMAN, Chloe", "officer_role": "director", "appointed_on": "2026-07-01"},
            {"name": "OLD, Person", "officer_role": "director", "resigned_on": "2025-01-01"},
        ],
        owners=[
            {
                "name": "Ms Chloe Newman",
                "natures_of_control": ["ownership-of-shares-75-to-100-percent"],
            }
        ],
    )
    result = merge.render("{{ cs01_data }}", build_context(client))
    assert "1 Example Street" in result.text
    assert "62020" in result.text
    assert "NEWMAN, Chloe" in result.text and "OLD, Person" not in result.text
    assert "ownership of shares 75 to 100 percent" in result.text
    assert "30/06/2027" in result.text
    assert "shareholders and share capital" in result.text


def test_outstanding_invoices_is_empty_until_stage_11():
    assert merge.render("[{{ outstanding_invoices }}]", ctx_for()).text == "[]"
