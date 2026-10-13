import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.companieshouse import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def company():
    return ClientFactory(company_number="09999901")


def addresses(c):
    return [
        ("companieshouse:add", [], "get"),
        ("companieshouse:preview", ["09999901"], "get"),
        ("companieshouse:preview", ["09999901"], "post"),
        ("companieshouse:tab", [c.pk], "get"),
        ("companieshouse:sync", [c.pk], "post"),
        ("companieshouse:fill_in", [c.pk], "post"),
        ("companieshouse:integrations", [], "get"),
    ]


def test_signed_out_users_are_sent_to_sign_in(client, company):
    for name, args, method in addresses(company):
        response = getattr(client, method)(reverse(name, args=args))
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_portal_users_are_refused(client, company):
    sign_in(client, portal_user())
    for name, args, method in addresses(company):
        assert getattr(client, method)(reverse(name, args=args)).status_code == 403, name


def test_integrations_needs_the_right(client):
    for person in (manager(), staff()):
        sign_in(client, person)
        assert client.get(reverse("companieshouse:integrations")).status_code == 403


def test_integrations_shows_key_state_but_never_the_key(client, settings):
    settings.COMPANIES_HOUSE_API_KEY = "made-up-key-value"
    sign_in(client, owner())
    page = client.get(reverse("companieshouse:integrations")).content.decode()
    assert "Key present" in page
    assert "made-up-key-value" not in page
    assert "Run sync now" in page
    settings.COMPANIES_HOUSE_API_KEY = ""
    assert "No key" in client.get(reverse("companieshouse:integrations")).content.decode()


def test_search_and_preview(client):
    sign_in(client, staff())
    page = client.get(reverse("companieshouse:add"), {"q": "example"}).content.decode()
    assert "EXAMPLE TRADING LTD" in page
    partial = client.get(reverse("companieshouse:add"), {"q": "zzz"}, HTTP_HX_REQUEST="true")
    assert "No companies found" in partial.content.decode()
    assert "<html" not in partial.content.decode()
    preview = client.get(reverse("companieshouse:preview", args=["09999901"])).content.decode()
    for text in ("EXAMPLE TRADING LTD", "31/12/2026", "Alice Sample", "EXAMPLE NOMINEES LIMITED"):
        assert text in preview
    assert Client.objects.count() == 0  # nothing saved by a preview


def test_preview_of_an_unknown_company_is_404(client):
    sign_in(client, staff())
    assert client.get(reverse("companieshouse:preview", args=["12345678"])).status_code == 404
    assert client.get(reverse("companieshouse:preview", args=["not-a-number"])).status_code == 404


def test_confirm_creates_the_client_and_opens_its_tab(client):
    boss = manager()
    sign_in(client, staff())
    response = client.post(
        reverse("companieshouse:preview", args=["09999901"]),
        {"status": "onboarding", "manager": boss.pk},
    )
    created = Client.objects.get(company_number="09999901")
    assert response.status_code == 302
    assert response["Location"] == reverse("companieshouse:tab", args=[created.pk])
    assert created.status == "onboarding" and created.manager == boss
    tab = client.get(response["Location"]).content.decode()
    for text in (
        "Sync now",
        "Alice Sample",
        "Verified",
        "Personal code: not on file",
        "Recent filings",
    ):
        assert text in tab
    # Confirming again fills in the same client.
    client.post(reverse("companieshouse:preview", args=["09999901"]), {"status": "active"})
    assert Client.objects.filter(company_number="09999901").count() == 1


def test_sync_now_and_fill_in(client, company):
    sign_in(client, staff())
    tab = client.get(reverse("companieshouse:tab", args=[company.pk])).content.decode()
    assert "Fill in from Companies House" in tab
    client.post(reverse("companieshouse:fill_in", args=[company.pk]))
    company.refresh_from_db()
    assert company.next_accounts_due is not None
    response = client.post(reverse("companieshouse:sync", args=[company.pk]), follow=True)
    assert "Nothing has changed" in response.content.decode()


def test_sync_now_reports_a_missing_company(client):
    gone = ClientFactory(company_number="12345678")
    sign_in(client, staff())
    response = client.post(reverse("companieshouse:sync", args=[gone.pk]), follow=True)
    assert "no company with that number" in response.content.decode()


def test_the_tab_shows_only_for_companies(client):
    sign_in(client, staff())
    person = ClientFactory(client_type=Client.Type.INDIVIDUAL)
    page = client.get(reverse("clients:detail", args=[person.pk])).content.decode()
    assert reverse("companieshouse:tab", args=[person.pk]) not in page
    company = ClientFactory()
    page = client.get(reverse("clients:detail", args=[company.pk])).content.decode()
    assert reverse("companieshouse:tab", args=[company.pk]) in page


def test_info_tab_fields_from_companies_house_are_read_only(client):
    sign_in(client, staff())
    company, _ = services.import_company(None, "09999901")
    form = client.get(reverse("clients:panel_edit", args=[company.pk, "company"])).content.decode()
    for name in ("next_accounts_due", "company_status", "registered_office", "sic_codes"):
        assert f'name="{name}"' not in form or "disabled" in form.split(f'name="{name}"')[1][:200]
    response = client.post(
        reverse("clients:panel_edit", args=[company.pk, "company"]),
        {
            "company_number": "09999901",
            "company_status": "dissolved",
            "next_accounts_due": "2030-01-01",
            "trading_name": "Example",
        },
    )
    assert response.status_code == 200
    company.refresh_from_db()
    assert company.company_status == "active"
    assert str(company.next_accounts_due) == "2026-12-31"
    assert company.trading_name == "Example"
    panel = client.get(reverse("clients:panel", args=[company.pk, "company"])).content.decode()
    assert "From Companies House" in panel


def test_the_read_only_list_matches_what_the_sync_writes():
    from apps.clients import panels

    assert set(panels.COMPANIES_HOUSE_FIELDS) == set(services.CH_FIELDS)
