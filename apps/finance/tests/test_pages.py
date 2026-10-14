from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory, manager, owner, sign_in, staff
from apps.clients.models import Client
from apps.clients.tests.factories import ClientContactFactory, ClientFactory, ContactFactory
from apps.comms import services as comms_services
from apps.comms.models import MessageTemplate, QueuedMessage
from apps.events.models import ActivityEvent
from apps.finance import chase, fees, invoicing, summary, sync, targets
from apps.finance.models import FinanceSettings, Target, XeroConnection, XeroContact, XeroInvoice
from apps.finance.tests.helpers import live_client
from apps.timekeeping import services as time_services

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 20)


def make_invoice(contact, number, day, net, status="AUTHORISED", due=None, **extra):
    return XeroInvoice.objects.create(
        xero_id=f"x-{number}",
        number=number,
        contact=contact,
        contact_name=contact.name,
        date=day,
        due_date=due or day + timedelta(days=14),
        status=status,
        sub_total=Decimal(net),
        total_tax=Decimal(net) * Decimal("0.2"),
        total=Decimal(net) * Decimal("1.2"),
        amount_due=Decimal(0) if status == "PAID" else Decimal(net) * Decimal("1.2"),
        **extra,
    )


def linked(client, name=None):
    return XeroContact.objects.create(
        xero_id=f"c-{client.pk}",
        name=name or client.name,
        client=client,
        match_state=XeroContact.Match.CONFIRMED,
    )


# ---------------------------------------------------------------- fees page


def test_fee_totals_split_by_service_manager_and_type():
    boss = owner(name="Boss Person")
    one = live_client("One Ltd", "accounts", 300, manager=boss)
    live_client("Two Ltd", "vat", 600, "quarterly", client_type=Client.Type.PARTNERSHIP)
    live_client("Three Ltd", "self_assessment", 2400, "annual")
    ClientFactory(name="Prospect Ltd", status=Client.Status.PROSPECT)
    data = fees.summary()
    assert data.total == Decimal("700.00")
    assert dict(data.by_service) == {
        "Accounts": Decimal("300.00"),
        "VAT Returns": Decimal("200.00"),
        "Self Assessment": Decimal("200.00"),
    }
    assert dict(data.by_manager) == {
        "Boss Person": Decimal("300.00"),
        "No manager": Decimal("400.00"),
    }
    assert data.by_type[0][0] == "Private limited company"
    assert [e["client"] for e in data.clients][0] == one


def test_fees_page_lists_clients_and_sorts(client):
    live_client("Zed Ltd", "accounts", 100)
    live_client("Alpha Ltd", "vat", 900)
    sign_in(client, owner())
    page = client.get(reverse("finance:fees")).content.decode()
    assert page.index("Alpha Ltd") < page.index("Zed Ltd")
    by_name = client.get(reverse("finance:fees"), {"sort": "name"}).content.decode()
    assert by_name.index("Alpha Ltd") < by_name.index("Zed Ltd")


def test_fee_changes_are_classified():
    from apps.services.models import FeeChange

    c = live_client("Change Ltd", "accounts", 100)
    cs = c.client_services.get()
    today = timezone.localdate()
    for old, new in [
        (None, 100),
        (100, 150),
        (150, 120),
    ]:
        FeeChange.objects.create(
            client_service=cs,
            old_amount=old,
            new_amount=new,
            old_frequency="monthly" if old else "",
            new_frequency="monthly",
            effective_on=today,
        )
    cs.state, cs.fee_amount = "ended", None
    cs.save()
    FeeChange.objects.create(
        client_service=cs,
        old_amount=120,
        new_amount=None,
        old_frequency="monthly",
        new_frequency="monthly",
        effective_on=today,
    )
    result = fees.changes_in_month(today.replace(day=1))
    assert [result[k]["count"] for k in ("new", "increased", "reduced", "ended")] == [1, 1, 1, 1]
    assert result["ended"]["amount"] == Decimal("-120.00")
    assert result["reduced"]["amount"] == Decimal("-30.00")


def test_hourly_return_lowest_first_flags_and_lists_no_time():
    cheap = live_client("Cheap Ltd", "accounts", 100)
    rich = live_client("Rich Ltd", "vat", 1000)
    live_client("Quiet Ltd", "payroll", 500)
    person = staff()
    day = date(2026, 10, 5)
    time_services.log_time(person, minutes=300, client=cheap, on_date=day)  # 5 h
    time_services.log_time(person, minutes=300, client=rich, on_date=day)
    result = fees.hourly_return(3, Decimal("60.00"), today=TODAY)
    assert [r.client for r in result["rows"]] == [cheap, rich]
    assert result["rows"][0].rate == Decimal("60.00")  # 3 x 100 / 5
    assert result["rows"][1].rate == Decimal("600.00")
    assert [r.client.name for r in result["no_time"]] == ["Quiet Ltd"]
    flagged = fees.hourly_return(3, Decimal("61.00"), today=TODAY)
    assert [r.client for r in flagged["below"]] == [cheap]
    assert fees.clients_below_rate(Decimal("61.00"), 3, TODAY) == 1


def test_hourly_return_window_excludes_older_time():
    c = live_client("Old Time Ltd", "accounts", 100)
    time_services.log_time(staff(), minutes=60, client=c, on_date=date(2026, 5, 4))
    assert fees.hourly_return(3, Decimal("60"), TODAY)["rows"] == []
    assert len(fees.hourly_return(12, Decimal("60"), TODAY)["rows"]) == 1


# ---------------------------------------------------------------- lists from Xero


def test_not_invoiced_after_the_set_day_only():
    a = live_client("Billed Ltd", "accounts", 300)
    live_client("Unbilled Ltd", "vat", 200)
    linked(a)
    make_invoice(XeroContact.objects.get(client=a), "INV-1", date(2026, 10, 1), 300)
    assert invoicing.not_invoiced(date(2026, 10, 10)) == []
    rows = invoicing.not_invoiced(date(2026, 10, 11))
    assert [r.client.name for r in rows] == ["Unbilled Ltd"]


def test_not_invoiced_ignores_voided_and_deleted_invoices_for_the_month():
    a = live_client("Voided Ltd", "accounts", 300)
    contact = linked(a)
    make_invoice(contact, "INV-1", date(2026, 10, 1), 300, status="VOIDED")
    make_invoice(contact, "INV-2", date(2026, 10, 2), 300, status="DELETED")
    assert [r.client for r in invoicing.not_invoiced(TODAY)] == [a]
    make_invoice(contact, "INV-3", date(2026, 10, 3), 300, status="DRAFT")
    assert invoicing.not_invoiced(TODAY) == []


def test_check_fee_flags_differences_over_a_pound():
    ok = live_client("Right Ltd", "accounts", 300)
    off = live_client("Wrong Ltd", "vat", 300)
    near = live_client("Near Ltd", "payroll", 300)
    make_invoice(linked(ok), "INV-1", date(2026, 10, 1), 300)
    make_invoice(linked(off), "INV-2", date(2026, 10, 1), 345)
    make_invoice(linked(near), "INV-3", date(2026, 10, 1), "300.90")
    rows = invoicing.check_fee(TODAY)
    assert [(r.client.name, r.difference) for r in rows] == [("Wrong Ltd", Decimal("45.00"))]


def test_check_fee_ignores_other_months_and_drafts():
    c = live_client("Other Month Ltd", "accounts", 300)
    contact = linked(c)
    make_invoice(contact, "INV-1", date(2026, 9, 1), 999)
    make_invoice(contact, "INV-2", date(2026, 10, 1), 999, status="DRAFT")
    assert invoicing.check_fee(TODAY) == []


def test_overdue_grouped_by_client_with_days():
    a, b = live_client("Late A", "accounts", 100), live_client("Late B", "vat", 100)
    make_invoice(linked(a), "INV-1", date(2026, 9, 1), 100, due=date(2026, 9, 15))
    make_invoice(
        XeroContact.objects.get(client=a), "INV-2", date(2026, 10, 1), 100, due=date(2026, 10, 15)
    )
    make_invoice(linked(b), "INV-3", date(2026, 10, 1), 100, due=date(2026, 10, 25))  # not yet due
    make_invoice(linked(live_client("Paid", "payroll", 1)), "INV-4", date(2026, 9, 1), 100, "PAID")
    groups = invoicing.overdue_groups(TODAY)
    assert [g.name for g in groups] == ["Late A"]
    assert groups[0].oldest_days == 35 and len(groups[0].invoices) == 2
    assert groups[0].total_due == Decimal("240.00")
    assert invoicing.overdue_total(TODAY) == Decimal("240.00")


def test_overdue_unmatched_contacts_are_grouped_by_name():
    stray = XeroContact.objects.create(xero_id="s1", name="Stray Customer")
    make_invoice(stray, "INV-9", date(2026, 9, 1), 100, due=date(2026, 9, 15))
    groups = invoicing.overdue_groups(TODAY)
    assert groups[0].client is None and groups[0].name == "Stray Customer"


# ---------------------------------------------------------------- chasing


def chase_world(days_overdue, *, with_contact=True):
    c = live_client("Chased Ltd", "accounts", 300)
    if with_contact:
        ClientContactFactory(
            client=c,
            contact=ContactFactory(first_name="Pat", email="pat@example.com"),
            is_main=True,
        )
    due = TODAY - timedelta(days=days_overdue)
    make_invoice(linked(c), "INV-77", due - timedelta(days=14), 300, due=due)
    return c


@pytest.mark.parametrize(
    "days, key",
    [
        (7, "fees_chase_7"),
        (13, "fees_chase_7"),
        (14, "fees_chase_14"),
        (29, "fees_chase_14"),
        (30, "fees_chase_30"),
        (90, "fees_chase_30"),
    ],
)
def test_template_is_chosen_by_the_oldest_invoice(days, key):
    chase_world(days)
    result = chase.draft_chase_emails(owner(), TODAY)
    message = QueuedMessage.objects.get()
    assert result["made"] == 1 and message.template.key == key
    assert "INV-77" in message.body_html and f"{days} days overdue" in message.body_html


def test_nothing_is_drafted_under_seven_days():
    chase_world(6)
    assert chase.draft_chase_emails(owner(), TODAY)["made"] == 0
    assert not QueuedMessage.objects.exists()


def test_chase_drafts_always_wait_for_approval_even_if_the_template_is_automatic():
    chase_world(20)
    MessageTemplate.objects.filter(key="fees_chase_14").update(send_mode="auto")
    chase.draft_chase_emails(owner(), TODAY)
    message = QueuedMessage.objects.get()
    assert message.state == QueuedMessage.State.NEEDS_APPROVAL
    assert message.approved_by is None and message.sent_at is None


def test_chase_drafts_need_the_fees_approval_right():
    chase_world(20)
    chase.draft_chase_emails(owner(), TODAY)
    message = QueuedMessage.objects.get()
    no_right = staff()  # staff hold comms.approve but not comms.approve_fees
    assert not comms_services.can_approve(no_right, message)
    assert comms_services.can_approve(manager(), message)
    with pytest.raises(Exception):  # noqa: B017, PT011
        comms_services.approve(message, no_right)
    comms_services.approve(message, manager())
    message.refresh_from_db()
    assert message.state == QueuedMessage.State.APPROVED


def test_chase_is_not_drafted_twice_but_escalates():
    chase_world(8)
    first = chase.draft_chase_emails(owner(), TODAY)
    again = chase.draft_chase_emails(owner(), TODAY)
    assert (first["made"], again["made"]) == (1, 0)
    later = chase.draft_chase_emails(owner(), TODAY + timedelta(days=10))  # now 18 days
    assert later["made"] == 1
    assert QueuedMessage.objects.count() == 2


def test_chase_skips_clients_without_an_address_or_match_or_who_have_left():
    chase_world(20, with_contact=False)
    stray = XeroContact.objects.create(xero_id="s1", name="Stray")
    make_invoice(stray, "INV-5", date(2026, 9, 1), 100, due=date(2026, 9, 10))
    gone = chase_world_other_status = live_client("Gone Ltd", "vat", 100)
    ClientContactFactory(client=gone, contact=ContactFactory(email="g@example.com"), is_main=True)
    make_invoice(linked(gone), "INV-6", date(2026, 8, 1), 100, due=date(2026, 8, 15))
    Client.objects.filter(pk=chase_world_other_status.pk).update(status=Client.Status.FORMER)
    result = chase.draft_chase_emails(owner(), TODAY)
    assert result["made"] == 0
    reasons = dict(result["skipped"])
    assert reasons["Stray"] == "Not matched to a client"
    assert "No contact with an email address" in reasons["Chased Ltd"]
    assert "former" in reasons["Gone Ltd"]


def test_chase_button_needs_the_owner(client):
    chase_world(20)
    sign_in(client, owner())
    response = client.post(reverse("finance:chase"))
    assert response.status_code == 302 and QueuedMessage.objects.count() == 1
    assert ActivityEvent.objects.filter(verb="finance.chase_drafted").exists()


def test_the_three_chase_templates_are_seeded_and_held():
    templates = MessageTemplate.objects.filter(group="fees")
    assert {t.key for t in templates} == {"fees_chase_7", "fees_chase_14", "fees_chase_30"}
    assert all(t.send_mode == "hold" and "{{ outstanding_invoices }}" in t.body for t in templates)


def test_outstanding_invoices_block_lists_overdue_invoices():
    from apps.comms import merge

    c = chase_world(20)
    ctx = comms_services.build_context(c)
    ctx.extra["today"] = TODAY
    text = merge.render("{{ outstanding_invoices }}", ctx)
    assert "INV-77" in text.html and "20" in text.html
    assert "INV-77" in text.text
    assert (
        merge.render(
            "[{{ outstanding_invoices }}]", comms_services.build_context(ClientFactory())
        ).text
        == "[]"
    )


# ---------------------------------------------------------------- targets


def test_spread_evenly_keeps_the_total():
    amounts = targets.spread_evenly(Decimal("10000"))
    assert len(amounts) == 12 and sum(amounts) == Decimal("10000.00")
    assert amounts[0] == Decimal("833.33") and amounts[-1] == Decimal("833.37")


def test_straight_line():
    amounts = targets.straight_line(Decimal("1000"), Decimal("2100"))
    assert amounts[0] == Decimal("1000.00") and amounts[-1] == Decimal("2100.00")
    assert amounts[1] == Decimal("1100.00") and len(amounts) == 12


def test_targets_page_saves_by_hand_and_clears(client):
    sign_in(client, owner())
    url = reverse("finance:targets")
    body = {"from": "2026-11", "action": "save", "m-2026-11": "3,000", "m-2026-12": "£3,250.50"}
    assert client.post(url, body).status_code == 302
    assert dict(Target.objects.values_list("month", "amount")) == {
        date(2026, 11, 1): Decimal("3000.00"),
        date(2026, 12, 1): Decimal("3250.50"),
    }
    client.post(url, {"from": "2026-11", "action": "save", "m-2026-12": "3250.50"})
    assert list(Target.objects.values_list("month", flat=True)) == [date(2026, 12, 1)]


def test_targets_page_quick_fills(client):
    sign_in(client, owner())
    url = reverse("finance:targets")
    client.post(url, {"from": "2026-11", "action": "yearly", "yearly": "36000"})
    assert Target.objects.count() == 12 and Target.objects.get(
        month=date(2026, 11, 1)
    ).amount == Decimal("3000.00")
    client.post(url, {"from": "2026-11", "action": "line", "first": "3000", "last": "4100"})
    assert Target.objects.get(month=date(2027, 10, 1)).amount == Decimal("4100.00")
    assert Target.objects.get(month=date(2026, 12, 1)).amount == Decimal("3100.00")


def test_targets_page_refuses_bad_figures(client):
    sign_in(client, owner())
    response = client.post(
        reverse("finance:targets"), {"from": "2026-11", "action": "save", "m-2026-11": "lots"}
    )
    assert response.status_code == 422 and not Target.objects.exists()
    assert (
        client.post(reverse("finance:targets"), {"from": "2026-11", "action": "yearly"}).status_code
        == 422
    )


# ---------------------------------------------------------------- forecast and summary pages


def test_forecast_page_has_chart_table_and_feedback(client):
    live_client("Steady Ltd", "accounts", 500, since=timezone.localdate() - timedelta(days=100))
    first = timezone.localdate().replace(day=1)
    from apps.core.dates import add_months

    Target.objects.create(month=add_months(first, 1), amount=Decimal("900"))
    sign_in(client, owner())
    text = client.get(reverse("finance:forecast")).content.decode()
    assert "<svg" in text and "Income forecast" in text
    assert "short of your target" in text and "Month by month" in text
    assert "<script" not in text.split("<main")[1]


def test_forecast_page_without_targets_says_so(client):
    sign_in(client, owner())
    assert "No targets are set" in client.get(reverse("finance:forecast")).content.decode()


def test_summary_page_and_text(client):
    live_client("Summed Ltd", "accounts", 500)
    sign_in(client, owner())
    page = client.get(reverse("finance:summary")).content.decode()
    for heading in ("Deadlines", "Work", "Requests", "Sales", "Compliance", "Money", "People"):
        assert f">{heading}</h2>" in page
    text = summary.as_text(summary.build())
    assert "MONEY" in text and "Recurring fees now: £500.00" in text


def test_summary_email_goes_only_to_owners():
    boss, other_boss = owner(email="boss@example.com"), owner(email="boss2@example.com")
    manager(email="manager@example.com")
    staff(email="staff@example.com")
    UserFactory(email="inactive@example.com", role_slug="owner", is_active=False)
    friday = timezone.make_aware(timezone.datetime(2026, 10, 16, 15, 5))
    result = summary.send_owner_summary(friday)
    assert result["sent"] == 2
    assert sorted(m.to[0] for m in mail.outbox) == ["boss2@example.com", "boss@example.com"]
    assert all("Owner summary" in m.subject for m in mail.outbox)
    assert boss and other_boss


def test_summary_email_waits_for_the_day_and_hour_and_sends_once():
    owner(email="boss@example.com")
    thursday = timezone.make_aware(timezone.datetime(2026, 10, 15, 16, 0))
    early = timezone.make_aware(timezone.datetime(2026, 10, 16, 14, 59))
    on_time = timezone.make_aware(timezone.datetime(2026, 10, 16, 15, 0))
    assert summary.send_owner_summary(thursday)["sent"] == 0
    assert summary.send_owner_summary(early)["sent"] == 0
    assert summary.send_owner_summary(on_time)["sent"] == 1
    assert summary.send_owner_summary(on_time + timedelta(hours=2))["sent"] == 0
    assert FinanceSettings.load().summary_last_sent_on == date(2026, 10, 16)
    next_friday = on_time + timedelta(days=7)
    assert summary.send_owner_summary(next_friday)["sent"] == 1


def test_summary_day_and_hour_are_settings():
    owner(email="boss@example.com")
    FinanceSettings.objects.update_or_create(
        pk=1, defaults={"summary_weekday": 0, "summary_hour": 8}
    )
    monday = timezone.make_aware(timezone.datetime(2026, 10, 19, 8, 30))
    assert summary.send_owner_summary(monday)["sent"] == 1


def test_summary_job_is_registered():
    from apps.jobs import registry

    assert registry.get("owner_summary") and registry.get("xero_sync")


def test_settings_page_saves(client):
    sign_in(client, owner())
    client.post(
        reverse("finance:settings"),
        {
            "target_hourly_rate": "75.00",
            "not_invoiced_after_day": "12",
            "default_start_days": "45",
            "summary_weekday": "3",
            "summary_hour": "9",
        },
    )
    saved = FinanceSettings.load()
    assert (saved.target_hourly_rate, saved.not_invoiced_after_day, saved.summary_hour) == (
        Decimal("75.00"),
        12,
        9,
    )
    bad = client.post(reverse("finance:settings"), {"target_hourly_rate": "x"})
    assert bad.status_code == 422


# ---------------------------------------------------------------- Xero screens


def test_matching_screen_confirms_ignores_and_unlinks(client):
    c = ClientFactory(name="Match Me Ltd")
    contact = XeroContact.objects.create(
        xero_id="m1", name="Match Me Limited", suggested_client=c, match_state="suggested"
    )
    sign_in(client, owner())
    assert "Match Me Ltd (suggested)" in client.get(reverse("finance:matching")).content.decode()
    client.post(reverse("finance:match_confirm", args=[contact.pk]), {"client": c.pk})
    contact.refresh_from_db()
    assert contact.client == c
    other = XeroContact.objects.create(xero_id="m2", name="Other")
    assert (
        "already linked"
        in client.post(
            reverse("finance:match_confirm", args=[other.pk]), {"client": c.pk}, follow=True
        ).content.decode()
    )
    client.post(reverse("finance:match_ignore", args=[other.pk]))
    other.refresh_from_db()
    assert other.match_state == "ignored"
    client.post(reverse("finance:match_unmatch", args=[contact.pk]))
    contact.refresh_from_db()
    assert contact.client is None


def test_connect_callback_checks_the_state_and_stores_the_connection(client, fake):
    sign_in(client, owner())
    response = client.get(reverse("finance:xero_connect"))
    assert response.status_code == 302 and response["Location"].startswith(
        "https://login.xero.com/"
    )
    state = client.session["xero_state"]
    bad = client.get(reverse("finance:xero_callback"), {"code": "abc", "state": "wrong"})
    assert bad.status_code == 403 and not XeroConnection.objects.exists()
    client.get(reverse("finance:xero_connect"))
    state = client.session["xero_state"]
    done = client.get(reverse("finance:xero_callback"), {"code": "abc", "state": state})
    assert (
        done.status_code == 302 and XeroConnection.objects.get().tenant_name == "Demo Practice Ltd"
    )
    assert client.session.get("xero_state") is None


def test_callback_without_a_state_in_the_session_is_refused(client):
    sign_in(client, owner())
    assert (
        client.get(reverse("finance:xero_callback"), {"code": "a", "state": "b"}).status_code == 403
    )


def test_integrations_page_shows_xero_to_the_owner_only(client, connection):
    sign_in(client, owner())
    text = client.get(reverse("companieshouse:integrations")).content.decode()
    assert "Demo Practice Ltd" in text and "Sync now" in text and "never shown here" in text
    assert "access-start" not in text and "refresh-start" not in text
    sign_in(client, manager())
    assert client.get(reverse("companieshouse:integrations")).status_code == 403


def test_a_broken_connection_is_shown_on_finance_pages(client, connection):
    connection.broken = True
    connection.last_error = "Xero refused the connection."
    connection.last_good_sync_at = timezone.make_aware(timezone.datetime(2026, 10, 1, 2, 30))
    connection.last_sync_at = timezone.now()
    connection.save()
    sign_in(client, owner())
    text = client.get(reverse("finance:invoices")).content.decode()
    assert "The Xero connection has a problem" in text and "01/10/2026 02:30" in text


def test_disconnect_and_sync_now(client, connection):
    from apps.jobs.models import JobLock

    sign_in(client, owner())
    client.post(reverse("finance:xero_sync"))
    assert JobLock.objects.get(name="xero_sync").requested_at is not None
    client.post(reverse("finance:xero_disconnect"))
    assert not XeroConnection.objects.exists()


def test_send_to_xero_button_creates_and_links(client, connection, fake):
    c = ClientFactory(name="Brand New Ltd")
    sign_in(client, owner())
    client.post(reverse("finance:send_to_xero", args=[c.pk]))
    assert XeroContact.objects.get(client=c).match_state == "confirmed"
    assert ActivityEvent.objects.filter(verb="finance.xero_contact_created", client=c).exists()


def test_xero_matching_events_are_logged(connection):
    c = ClientFactory(name="Logged Ltd")
    contact = XeroContact.objects.create(xero_id="l1", name="Logged")
    sync.confirm_match(owner(), contact, c)
    assert ActivityEvent.objects.filter(verb="finance.xero_matched", client=c).exists()
