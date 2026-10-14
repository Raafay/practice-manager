import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection as db_connection
from django.utils import timezone

from apps.accounts.tests.factories import owner, staff
from apps.clients.tests.factories import ClientFactory
from apps.events.models import Notification
from apps.finance import invoicing, sync, xero
from apps.finance.models import (
    XeroConnection,
    XeroContact,
    XeroCreditNote,
    XeroInvoice,
)
from apps.finance.xero_fake import rate_limited

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- tokens


def test_token_is_not_refreshed_while_good(connection, fake):
    token, tenant = xero.XeroClient().access_token()
    assert token == "access-start" and tenant == connection.tenant_id
    assert fake.token_calls == 0


def test_refresh_rotates_both_tokens(expired, fake):
    token, _ = xero.XeroClient().access_token()
    expired.refresh_from_db()
    assert token == "access-1"
    assert (expired.access_token, expired.refresh_token) == ("access-1", "refresh-1")
    assert expired.expires_at > timezone.now() + timedelta(minutes=20)
    form = fake.requests[0]["form"]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "refresh-start"


def test_tokens_are_stored_encrypted(expired, fake):
    xero.XeroClient().access_token()
    with db_connection.cursor() as cursor:
        cursor.execute("select access_token, refresh_token from finance_xeroconnection")
        raw = cursor.fetchone()
    assert "access-1" not in raw[0] and "refresh-1" not in raw[1]


def test_second_call_after_a_refresh_does_not_refresh_again(expired, fake):
    xero.XeroClient().access_token()
    xero.XeroClient().access_token()
    assert fake.token_calls == 1


@pytest.mark.django_db(transaction=True)
def test_two_refreshes_at_once_spend_the_token_once(fake):
    XeroConnection.objects.create(
        tenant_id="t1",
        access_token="old",
        refresh_token="refresh-start",
        expires_at=timezone.now() - timedelta(minutes=5),
    )
    fake.refresh_delay = 0.3
    seen, errors = [], []

    def worker():
        try:
            seen.append(xero.XeroClient().access_token()[0])
        except Exception as error:  # noqa: BLE001
            errors.append(error)
        finally:
            db_connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert fake.token_calls == 1
    assert seen == ["access-1", "access-1"]
    assert XeroConnection.objects.get().refresh_token == "refresh-1"


def test_refused_refresh_is_an_auth_failure(expired, fake):
    from apps.finance.xero import Response

    fake.queue.append(Response(400, {}, b'{"error":"invalid_grant"}'))
    with pytest.raises(xero.AuthFailed):
        xero.XeroClient().access_token()


def test_not_connected():
    with pytest.raises(xero.NotConnected):
        xero.XeroClient().access_token()


def test_consent_address_asks_for_the_narrow_scopes(settings):
    settings.SITE_URL = "https://pm.example.com"
    url = xero.authorise_url("abc")
    assert "scope=offline_access+accounting.contacts+accounting.invoices.read" in url
    assert "accounting.payments.read" in url
    assert "redirect_uri=https%3A%2F%2Fpm.example.com%2Fintegrations%2Fxero%2Fcallback" in url
    assert "state=abc" in url


def test_exchange_code_stores_the_organisation(fake):
    user = owner()
    conn = xero.XeroClient().exchange_code("the-code", user)
    assert conn.tenant_name == "Demo Practice Ltd" and conn.connected_by == user
    assert conn.access_token == "access-1" and conn.refresh_token == "refresh-1"
    assert fake.requests[0]["form"]["code"] == "the-code"
    assert XeroConnection.objects.count() == 1


# ---------------------------------------------------------------- calls


def test_data_calls_send_the_tenant_and_token(connection, fake):
    list(xero.XeroClient().contacts())
    headers = fake.requests[-1]["headers"]
    assert headers["xero-tenant-id"] == connection.tenant_id
    assert headers["Authorization"] == "Bearer access-start"


def test_429_obeys_retry_after_then_carries_on(connection, fake):
    fake.queue.append(rate_limited(7))
    slept = []
    client = xero.XeroClient(sleep=slept.append)
    assert len(list(client.contacts())) == 4
    assert slept == [7]


def test_429_with_a_long_wait_gives_up(connection, fake):
    fake.queue.append(rate_limited(600))
    with pytest.raises(xero.RateLimited):
        list(xero.XeroClient(sleep=lambda s: None).contacts())


def test_repeated_429_gives_up(connection, fake):
    fake.queue.extend(rate_limited(1) for _ in range(5))
    with pytest.raises(xero.RateLimited):
        list(xero.XeroClient(sleep=lambda s: None).invoices())


def test_invoices_are_read_page_by_page(connection, fake):
    items = list(xero.XeroClient().invoices())
    assert len(items) == 8
    pages = [r["params"]["page"] for r in fake.requests if r["path"].endswith("Invoices")]
    assert pages == [1, 2]
    assert fake.requests[-1]["params"]["where"] == 'Type=="ACCREC"'


def test_if_modified_since_is_sent(connection, fake):
    since = timezone.now() - timedelta(days=1)
    list(xero.XeroClient().invoices(since=since))
    assert "If-Modified-Since" in fake.requests[-1]["headers"]


# ---------------------------------------------------------------- the sync


def test_sync_reads_everything_and_reads_only(connection, fake):
    log = sync.run_sync()
    assert log.state == "done"
    assert log.counts == {"contacts": 4, "invoices": 8, "credit_notes": 1}
    assert XeroInvoice.objects.count() == 8
    assert all(r["method"] == "GET" for r in fake.requests if "api.xro" in r["url"])
    connection.refresh_from_db()
    assert connection.last_good_sync_at and not connection.broken
    assert connection.modified_since < connection.last_good_sync_at


def test_sync_is_safe_to_run_twice(connection, fake):
    sync.run_sync()
    first = (
        XeroInvoice.objects.count(),
        XeroContact.objects.count(),
        XeroCreditNote.objects.count(),
    )
    sync.run_sync()
    assert (
        XeroInvoice.objects.count(),
        XeroContact.objects.count(),
        XeroCreditNote.objects.count(),
    ) == first


def test_second_sync_asks_only_for_changes(connection, fake):
    sync.run_sync()
    sync.run_sync()
    second = [r for r in fake.requests if "api.xro" in r["url"]][-3:]
    assert all("If-Modified-Since" in r["headers"] for r in second)


def test_both_date_forms_are_parsed(connection, fake):
    sync.run_sync()
    string_form = XeroInvoice.objects.get(number="INV-0101")
    ms_form = XeroInvoice.objects.get(number="INV-0103")
    assert (string_form.date, string_form.due_date) == (date(2026, 10, 1), date(2026, 10, 15))
    assert (ms_form.date, ms_form.due_date) == (date(2026, 10, 1), date(2026, 10, 15))
    assert sync.parse_date("/Date(1790000000000+0000)/") == date(2026, 9, 21)


def test_invoice_amounts_and_states_are_stored(connection):
    sync.run_sync()
    invoice = XeroInvoice.objects.get(number="INV-0101")
    assert (invoice.sub_total, invoice.total_tax, invoice.total) == (
        Decimal("300.00"),
        Decimal("60.00"),
        Decimal("360.00"),
    )
    assert invoice.amount_due == Decimal("360.00") and invoice.status == "AUTHORISED"
    assert set(XeroInvoice.objects.values_list("status", flat=True)) == {
        "AUTHORISED",
        "PAID",
        "DRAFT",
        "VOIDED",
        "DELETED",
    }


def test_not_connected_sync_does_nothing(fake):
    assert sync.run_sync() is None
    assert fake.requests == []


def test_broken_connection_keeps_last_good_sync_and_tells_the_owner(connection, fake):
    boss = owner()
    sync.run_sync()
    good = XeroConnection.objects.get().last_good_sync_at
    connection.refresh_from_db()
    connection.expires_at = timezone.now() - timedelta(minutes=1)
    connection.save()
    from apps.finance.xero import Response

    fake.queue.append(Response(400, {}, b'{"error":"invalid_grant"}'))
    log = sync.run_sync()
    assert log.state == "failed"
    state = sync.status()
    assert state["state"] == "broken" and state["last_good"] == good
    assert Notification.objects.filter(user=boss, kind="xero_broken").count() == 1
    sync.run_sync()  # the same day: still one notice
    assert Notification.objects.filter(user=boss, kind="xero_broken").count() == 1
    assert not Notification.objects.filter(user=staff(), kind="xero_broken").exists()


def test_failed_sync_keeps_the_old_data(connection, fake):
    sync.run_sync()
    before = XeroInvoice.objects.count()
    fake.queue.extend(rate_limited(600) for _ in range(1))
    sync.run_sync(transport=fake)
    assert XeroInvoice.objects.count() == before


# ---------------------------------------------------------------- "invoiced"


def test_invoiced_excludes_draft_voided_deleted_and_subtracts_credit_notes(connection):
    sync.run_sync()
    # September: INV-0102 300 (paid) + INV-0108 400 (paid) + INV-0105 voided (ignored)
    # less credit note CN-0001 of 50 net dated 20/09/2026.
    assert invoicing.invoiced_in_month(date(2026, 9, 1)) == Decimal("650.00")
    # October: INV-0101 300 + INV-0103 250; the draft and the deleted one are left out.
    assert invoicing.invoiced_in_month(date(2026, 10, 1)) == Decimal("550.00")
    assert invoicing.invoiced_in_month(date(2026, 8, 1)) == Decimal("250.00")


def test_credit_notes_that_are_not_authorised_do_not_count(connection):
    sync.run_sync()
    XeroCreditNote.objects.update(status="DRAFT")
    assert invoicing.invoiced_in_month(date(2026, 9, 1)) == Decimal("700.00")


# ---------------------------------------------------------------- matching


def test_suggestions_by_name(connection):
    exact = ClientFactory(name="Example Trading Limited")
    close = ClientFactory(name="Harbour Cafe")
    ClientFactory(name="Something Else Ltd")
    sync.run_sync()
    by_name = {c.name: c for c in XeroContact.objects.all()}
    assert by_name["Example Trading Ltd"].suggested_client == exact
    assert by_name["Harbour Cafe Limited"].suggested_client == close
    assert by_name["Zed Unknown Co"].suggested_client is None
    assert by_name["Marlow & Pine LLP"].match_state == "none"
    assert by_name["Example Trading Ltd"].match_state == "suggested"


def test_suggestions_are_not_confirmed_matches(connection):
    ClientFactory(name="Example Trading Ltd")
    sync.run_sync()
    assert not XeroContact.objects.filter(client__isnull=False).exists()
    assert invoicing.client_invoice_summary(ClientFactory())["invoices"] == []


def test_confirm_unmatch_ignore(connection):
    client = ClientFactory(name="Example Trading Ltd")
    sync.run_sync()
    contact = XeroContact.objects.get(name="Example Trading Ltd")
    boss = owner()
    sync.confirm_match(boss, contact, client)
    contact.refresh_from_db()
    assert contact.client == client and contact.match_state == "confirmed"
    summary = invoicing.client_invoice_summary(client, today=date(2026, 10, 20))
    assert {i.number for i in summary["invoices"]} == {"INV-0101", "INV-0102"}
    sync.refresh_suggestions()  # a confirmed match is left alone
    contact.refresh_from_db()
    assert contact.client == client
    sync.unmatch(boss, contact)
    contact.refresh_from_db()
    assert contact.client is None
    sync.ignore(boss, contact)
    contact.refresh_from_db()
    sync.refresh_suggestions()  # an ignored contact stays ignored
    contact.refresh_from_db()
    assert contact.match_state == "ignored"


def test_send_to_xero_creates_and_links_a_contact(connection, fake):
    client = ClientFactory(name="New Client Ltd")
    contact = sync.send_contact(owner(), client)
    assert contact.client == client and contact.match_state == "confirmed"
    post = [r for r in fake.requests if r["method"] == "POST" and r["path"].endswith("Contacts")][0]
    assert post["body"]["Contacts"][0]["Name"] == "New Client Ltd"
    with pytest.raises(ValueError):
        sync.send_contact(owner(), client)
