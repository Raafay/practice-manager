"""Every Finance address is for the owner only: manager and staff get 403, and none of the
owner's figures leak into a page those users can open."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.finance import sync
from apps.finance.models import Target, XeroContact
from apps.finance.tests.helpers import live_client
from apps.timekeeping import services as time_services

pytestmark = pytest.mark.django_db

TARGET = Decimal("7777.00")


@pytest.fixture
def world(connection):
    today = timezone.localdate()
    a = live_client("Fee Client A", "accounts", 410, since=today - timedelta(days=200))
    live_client("Fee Client B", "vat", 1230, "quarterly", since=today - timedelta(days=400))
    ClientFactory(name="Another Co Ltd", status=Client.Status.PROSPECT)
    sync.run_sync()
    contact = XeroContact.objects.get(name="Example Trading Ltd")
    sync.confirm_match(owner(), contact, a)
    Target.objects.create(month=today.replace(day=1), amount=TARGET)
    time_services.log_time(staff(), minutes=60, client=a)
    return {"client": a, "contact": contact}


def addresses(w):
    pk, cpk = w["contact"].pk, w["client"].pk
    return [
        ("finance:fees", [], "get"),
        ("finance:invoices", [], "get"),
        ("finance:chase", [], "post"),
        ("finance:targets", [], "get"),
        ("finance:targets", [], "post"),
        ("finance:forecast", [], "get"),
        ("finance:summary", [], "get"),
        ("finance:settings", [], "get"),
        ("finance:settings", [], "post"),
        ("finance:matching", [], "get"),
        ("finance:match_confirm", [pk], "post"),
        ("finance:match_unmatch", [pk], "post"),
        ("finance:match_ignore", [pk], "post"),
        ("finance:xero_connect", [], "get"),
        ("finance:xero_callback", [], "get"),
        ("finance:xero_disconnect", [], "post"),
        ("finance:xero_sync", [], "post"),
        ("finance:send_to_xero", [cpk], "post"),
    ]


def call(client, name, args, method):
    url = reverse(name, args=args)
    return client.get(url) if method == "get" else client.post(url, {})


def test_signed_out_users_are_sent_to_sign_in(client, world):
    for name, args, method in addresses(world):
        assert "/login/" in call(client, name, args, method)["Location"], name


@pytest.mark.parametrize("make", [manager, staff])
def test_manager_and_staff_get_403_on_every_finance_address(client, world, make):
    sign_in(client, make())
    for name, args, method in addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_a_portal_user_gets_403(client, world):
    sign_in(client, portal_user())
    for name, args, method in addresses(world):
        assert call(client, name, args, method).status_code == 403, name


def test_the_owner_can_open_every_page(client, world):
    sign_in(client, owner())
    for name in ("fees", "invoices", "targets", "forecast", "summary", "settings", "matching"):
        assert client.get(reverse(f"finance:{name}")).status_code == 200, name


OWNER_ONLY_TEXT = [
    "Recurring fees now",
    "Weighted pipeline",
    "Hourly return",
    "Not invoiced this month",
    "Overdue fees",
    "Targets",
    "7,777.00",
    "Owner summary",
    "Forecast for",
]


@pytest.mark.parametrize("make", [manager, staff])
def test_no_finance_figure_appears_in_pages_those_users_can_open(client, world, make):
    sign_in(client, make())
    c = world["client"]
    pages = [
        reverse("overview"),
        reverse("clients:list"),
        reverse("clients:detail", args=[c.pk]),
        reverse("tasks:list"),
        reverse("tasks:workload"),
        reverse("timekeeping:sheet"),
        reverse("timekeeping:client_tab", args=[c.pk]),
        reverse("pipeline:prospects"),
        reverse("reports:index"),
        reverse("core:settings"),
        reverse("comms:queue"),
        reverse("events:notifications"),
    ]
    opened = 0
    for url in pages:
        response = client.get(url)
        if response.status_code != 200:
            continue
        opened += 1
        text = response.content.decode()
        for needle in OWNER_ONLY_TEXT:
            assert needle not in text, f"{needle!r} leaked into {url}"
    assert opened >= 8  # the scan reads real pages, not error pages
    assert 'href="/finance/' not in client.get(reverse("overview")).content.decode()


def test_the_nav_shows_finance_to_the_owner_only(client, world):
    sign_in(client, owner())
    assert 'href="/finance/fees/"' in client.get(reverse("overview")).content.decode()


def test_the_overview_panel_is_for_the_owner_only(client, world):
    sign_in(client, owner())
    assert "Recurring fees now" in client.get(reverse("overview")).content.decode()


def test_the_client_fees_tab_needs_fees_view(client, world):
    c = world["client"]
    url = reverse("finance:client_fees", args=[c.pk])
    sign_in(client, manager())
    assert client.get(url).status_code == 200  # managers hold fees.view
    from apps.pipeline.tests.helpers import no_fee_staff

    sign_in(client, no_fee_staff())
    assert client.get(url).status_code == 403
    assert (
        "Fees and invoices"
        not in client.get(reverse("clients:detail", args=[c.pk])).content.decode()
    )


def test_the_client_fees_tab_shows_invoices_for_a_matched_client(client, world):
    sign_in(client, manager())
    text = client.get(reverse("finance:client_fees", args=[world["client"].pk])).content.decode()
    assert "INV-0101" in text and "Agreed fees" in text and "Example Trading Ltd" in text


def test_the_client_fees_tab_for_an_unmatched_client_says_so(client, world):
    sign_in(client, manager())
    other = ClientFactory(name="Unlinked Co Ltd")
    text = client.get(reverse("finance:client_fees", args=[other.pk])).content.decode()
    assert "not linked to a Xero contact" in text


def test_staff_cannot_send_a_client_to_xero_or_open_the_callback(client, world):
    sign_in(client, staff())
    c = world["client"]
    assert client.post(reverse("finance:send_to_xero", args=[c.pk])).status_code == 403
    assert (
        client.get(reverse("finance:xero_callback"), {"code": "x", "state": "y"}).status_code == 403
    )
