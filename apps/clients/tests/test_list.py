import csv
import io

import pytest
from django.urls import reverse

from apps import events  # noqa: F401
from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients.models import Client, SavedView
from apps.events.models import ActivityEvent

from .factories import ClientContactFactory, ClientFactory, ContactFactory, TagFactory

pytestmark = pytest.mark.django_db


def names(response):
    return [c.name for c in response.context["page"].object_list]


def test_list_shows_active_onboarding_and_paused_by_default(client):
    ClientFactory(name="Active One", status="active")
    ClientFactory(name="Onboarding One", status="onboarding")
    ClientFactory(name="Paused One", status="paused")
    ClientFactory(name="Prospect One", status="prospect")
    ClientFactory(name="Former One", status="former")
    ClientFactory(name="Lost One", status="lost")
    sign_in(client, staff())
    shown = names(client.get(reverse("clients:list")))
    assert set(shown) == {"Active One", "Onboarding One", "Paused One"}


def test_status_filter_can_show_prospects_and_lost(client):
    ClientFactory(name="Active One")
    ClientFactory(name="Prospect One", status="prospect")
    ClientFactory(name="Lost One", status="lost")
    sign_in(client, staff())
    shown = names(client.get(reverse("clients:list"), {"status": ["prospect", "lost"]}))
    assert set(shown) == {"Prospect One", "Lost One"}


def test_filters_by_type_manager_partner_team_and_tag(client):
    boss = owner()
    other = staff()
    tag = TagFactory(name="VIP")
    match = ClientFactory(name="Match", client_type="sole_trader", manager=boss, partner=other)
    match.tags.add(tag)
    ClientFactory(name="Other type", client_type="ltd", manager=boss, partner=other)
    ClientFactory(name="Other manager", client_type="sole_trader", manager=other, partner=other)
    sign_in(client, boss)
    response = client.get(
        reverse("clients:list"),
        {"client_type": "sole_trader", "manager": boss.pk, "partner": other.pk, "tag": tag.pk},
    )
    assert names(response) == ["Match"]


def test_archived_clients_are_hidden_unless_asked_for(client):
    from django.utils import timezone

    ClientFactory(name="Visible")
    ClientFactory(name="Hidden", archived_at=timezone.now(), archive_reason="Test")
    sign_in(client, staff())
    assert names(client.get(reverse("clients:list"))) == ["Visible"]
    assert names(client.get(reverse("clients:list"), {"archived": "only"})) == ["Hidden"]


def test_sorting_and_column_choice(client):
    ClientFactory(name="Beta", accounting_ref_month=3, accounting_ref_day=31)
    ClientFactory(name="Alpha", accounting_ref_month=12, accounting_ref_day=31)
    sign_in(client, staff())
    ascending = names(client.get(reverse("clients:list"), {"sort": "name"}))
    descending = names(client.get(reverse("clients:list"), {"sort": "-name"}))
    assert ascending == ["Alpha", "Beta"] and descending == ["Beta", "Alpha"]
    by_year_end = names(client.get(reverse("clients:list"), {"sort": "year_end"}))
    assert by_year_end == ["Beta", "Alpha"]
    response = client.get(reverse("clients:list"), {"cols": ["email", "phone"], "sort": "nonsense"})
    assert [key for key, _ in response.context["columns"]] == ["name", "email", "phone"]
    assert response.status_code == 200


def test_search_matches_name_number_contact_and_email(client):
    target = ClientFactory(name="Quiet Harbour Ltd", company_number="ZZ000123")
    link = ClientContactFactory(
        client=target,
        contact=ContactFactory(first_name="Odette", last_name="Marsh", email="odette@example.com"),
    )
    ClientFactory(name="Unrelated Ltd")
    sign_in(client, staff())
    for term in ["harbour", "ZZ000123", "odette", "marsh", "Odette Marsh", "odette@example"]:
        assert names(client.get(reverse("clients:list"), {"q": term})) == ["Quiet Harbour Ltd"], (
            term
        )
    assert link.client == target


def test_search_dropdown_needs_two_characters_and_shows_status(client):
    ClientFactory(name="Prospect Co", status="prospect")
    sign_in(client, staff())
    short = client.get(reverse("clients:search_dropdown"), {"q": "P"})
    assert b"Prospect Co" not in short.content
    found = client.get(reverse("clients:search_dropdown"), {"q": "Prospect"})
    assert b"Prospect Co" in found.content and b"Prospect</span>" in found.content


def test_search_results_page_lists_clients_and_people(client):
    ClientFactory(name="Findable Ltd")
    ContactFactory(first_name="Findable", last_name="Person")
    sign_in(client, staff())
    response = client.get(reverse("clients:search"), {"q": "findable"})
    assert b"Findable Ltd" in response.content and b"Findable Person" in response.content


def test_saved_views_are_private_or_shared(client):
    me, you = staff(), staff()
    ClientFactory(name="Alpha Trader", client_type="sole_trader")
    ClientFactory(name="Beta Ltd", client_type="ltd")
    sign_in(client, me)
    response = client.post(
        reverse("clients:view_save"),
        {"name": "Sole traders", "query": "client_type=sole_trader&cols=email&sort=-name"},
    )
    saved = SavedView.objects.get()
    assert response["Location"].endswith(f"?view={saved.pk}")
    assert saved.owner == me and not saved.shared
    assert saved.filters == {"client_type": ["sole_trader"]}
    assert saved.columns == ["name", "email"] and saved.sort == "-name"
    applied = client.get(reverse("clients:list"), {"view": saved.pk})
    assert names(applied) == ["Alpha Trader"]
    assert [k for k, _ in applied.context["columns"]] == ["name", "email"]

    other = type(client)()
    sign_in(other, you)
    assert names(other.get(reverse("clients:list"), {"view": saved.pk})) == [
        "Alpha Trader",
        "Beta Ltd",
    ]  # not shared: ignored
    saved.shared = True
    saved.save()
    assert names(other.get(reverse("clients:list"), {"view": saved.pk})) == ["Alpha Trader"]
    # Only the maker or the owner can delete it.
    assert other.post(reverse("clients:view_delete", args=[saved.pk])).status_code == 403
    assert client.post(reverse("clients:view_delete", args=[saved.pk])).status_code == 302
    assert not SavedView.objects.exists()


def test_export_needs_the_right_and_is_logged(client):
    ClientFactory(name="=SUM(A1)")
    ClientFactory(name="Normal Ltd")
    sign_in(client, staff())
    assert client.get(reverse("clients:export")).status_code == 403
    assert not ActivityEvent.objects.filter(verb="export.run").exists()

    sign_in(client, manager())
    response = client.get(reverse("clients:export"), {"cols": ["email"]})
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["Name", "Email"]
    assert ["'=SUM(A1)", ""] in rows  # not treated as a formula by a spreadsheet
    event = ActivityEvent.objects.get(verb="export.run")
    assert event.data["rows"] == 2


def test_export_keeps_the_current_filters(client):
    ClientFactory(name="Sole", client_type="sole_trader")
    ClientFactory(name="Limited", client_type="ltd")
    sign_in(client, owner())
    response = client.get(reverse("clients:export"), {"client_type": "sole_trader"})
    assert b"Sole" in response.content and b"Limited" not in response.content


def test_export_asks_for_the_password_again_when_it_is_old(client):
    sign_in(client, owner(), recent_password=False)
    response = client.get(reverse("clients:export"))
    assert response.status_code == 302
    assert "reauthenticate" in response["Location"] or "password" in response["Location"]
    assert Client.objects.count() == 0
