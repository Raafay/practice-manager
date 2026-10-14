import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory, manager, owner, portal_user, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.services import deadlines, services
from apps.services.models import ClientService, Deadline, FeeChange, Service

from .factories import company, service, take

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def world():
    client = company(vat_frequency="monthly")
    cs = take(client, "vat", starts_on=TODAY - timedelta(days=30), fee_amount=Decimal("100.00"))
    deadlines.generate_for_client(client)
    return {
        "client": client,
        "cs": cs,
        "deadline": client.deadlines.order_by("due_date").first(),
        "service": service("bookkeeping"),
    }


def addresses(w):
    c = w["client"].pk
    d, cs, s = w["deadline"].pk, w["cs"].pk, w["service"]
    return [
        ("services:list", [], "get"),
        ("services:add", [], "get"),
        ("services:edit", [s.pk], "get"),
        ("services:move", [s.pk, "up"], "post"),
        ("services:toggle", [s.pk], "post"),
        ("services:panel", [c], "get"),
        ("services:switch_on", [c, s.pk], "get"),
        ("services:settings", [c, cs], "get"),
        ("services:switch_off", [c, cs], "get"),
        ("services:fee", [c, cs], "post"),
        ("services:client_deadlines", [c], "get"),
        ("services:deadline_done", [c, d], "get"),
        ("services:deadline_not_required", [c, d], "get"),
        ("services:deadline_reopen", [c, d], "get"),
        ("services:deadline_date", [c, d], "get"),
        ("reports:index", [], "get"),
        ("services:report_deadlines", [], "get"),
        ("services:report_deadlines_export", [], "get"),
    ]


def test_every_address_sends_signed_out_users_to_sign_in(client, world):
    for name, args, method in addresses(world):
        response = getattr(client, method)(reverse(name, args=args))
        assert response.status_code == 302, name
        assert "/login/" in response["Location"], name


def test_every_address_refuses_portal_users(client, world):
    sign_in(client, portal_user())
    for name, args, method in addresses(world):
        assert getattr(client, method)(reverse(name, args=args)).status_code == 403, name


@pytest.mark.parametrize(
    ("name", "method", "who"),
    [
        ("services:list", "get", staff),
        ("services:add", "get", staff),
        ("services:edit", "get", staff),
        ("services:move", "post", staff),
        ("services:toggle", "post", staff),
        ("services:report_deadlines_export", "get", staff),
    ],
)
def test_pages_that_need_a_right_refuse_everyone_without_it(client, world, name, method, who):
    sign_in(client, who())
    args = {
        "services:edit": [world["service"].pk],
        "services:move": [world["service"].pk, "up"],
        "services:toggle": [world["service"].pk],
    }.get(name, [])
    assert getattr(client, method)(reverse(name, args=args)).status_code == 403


def test_staff_can_open_the_pages(client, world):
    sign_in(client, owner())
    for name, args, method in addresses(world):
        if method != "get" or name == "services:report_deadlines_export":
            continue
        assert client.get(reverse(name, args=args)).status_code == 200, name


def test_an_unknown_client_service_or_deadline_is_404_and_cannot_cross_clients(client, world):
    sign_in(client, owner())
    other = company()
    assert (
        client.get(reverse("services:settings", args=[other.pk, world["cs"].pk])).status_code == 404
    )
    assert (
        client.get(
            reverse("services:deadline_done", args=[other.pk, world["deadline"].pk])
        ).status_code
        == 404
    )
    assert client.get(reverse("services:client_deadlines", args=[999999])).status_code == 404


# ---------------------------------------------------------------- the Services panel


def test_the_info_tab_shows_the_services_panel_with_totals(client, world):
    take(world["client"], "bookkeeping", fee_amount=Decimal("300.00"), fee_frequency="quarterly")
    sign_in(client, owner())
    html = client.get(reverse("clients:detail", args=[world["client"].pk])).content.decode()
    assert 'id="services-panel"' in html
    assert "VAT Returns" in html
    assert "£200.00" in html  # 100.00 monthly + 100.00 (300 / 3)


def test_only_services_that_apply_to_the_client_type_are_listed(client):
    sole = company(client_type="sole_trader")
    sign_in(client, owner())
    html = client.get(reverse("services:panel", args=[sole.pk])).content.decode()
    assert "Self Assessment" in html
    assert "Partnership Return" not in html
    assert "CT600" not in html


def test_fees_are_hidden_without_the_right(client, world):
    role = Role.objects.create(slug="no-fees", name="No fees", rights=[])
    person = UserFactory(role=role)
    sign_in(client, person)
    html = client.get(reverse("services:panel", args=[world["client"].pk])).content.decode()
    assert "VAT Returns" in html
    assert "fee_amount" not in html
    assert "Monthly total" not in html
    assert "100.00" not in html
    response = client.post(
        reverse("services:fee", args=[world["client"].pk, world["cs"].pk]),
        {"fee_amount": "5", "fee_frequency": "monthly"},
    )
    assert response.status_code == 403


def test_saving_a_fee_logs_the_change(client, world):
    boss = owner()
    sign_in(client, boss)
    response = client.post(
        reverse("services:fee", args=[world["client"].pk, world["cs"].pk]),
        {"fee_amount": "£1,200.00", "fee_frequency": "annual"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    world["cs"].refresh_from_db()
    assert (world["cs"].fee_amount, world["cs"].fee_frequency) == (Decimal("1200.00"), "annual")
    assert FeeChange.objects.filter(client_service=world["cs"], changed_by=boss).exists()
    assert ActivityEvent.objects.filter(verb="service.fee_changed").exists()
    assert "About £100.00 a month" in response.content.decode()


def test_a_bad_fee_shows_an_error_and_changes_nothing(client, world):
    sign_in(client, owner())
    response = client.post(
        reverse("services:fee", args=[world["client"].pk, world["cs"].pk]),
        {"fee_amount": "lots", "fee_frequency": "monthly"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 422
    assert "Enter the fee as a number" in response.content.decode()
    world["cs"].refresh_from_db()
    assert world["cs"].fee_amount == Decimal("100.00")


def test_switching_on_a_service_from_the_dialog(client):
    target = company()
    sign_in(client, owner())
    url = reverse("services:switch_on", args=[target.pk, service("bookkeeping").pk])
    assert client.get(url).status_code == 200
    response = client.post(
        url,
        {
            "starts_on": "2026-10-01",
            "fee_amount": "150",
            "fee_frequency": "monthly",
            "frequency": "monthly",
            "end_month": "12",
            "due_days": "14",
            "notes": "",
        },
    )
    assert response.status_code == 302
    cs = ClientService.objects.get(client=target)
    assert cs.state == "active"
    assert cs.fee_amount == Decimal("150.00")
    assert cs.settings["frequency"] == "monthly"
    assert cs.settings["due_days"] == 14
    assert cs.starts_on == date(2026, 10, 1)


def test_switching_on_vat_writes_the_settings_to_the_client(client):
    target = company()
    sign_in(client, owner())
    response = client.post(
        reverse("services:switch_on", args=[target.pk, service("vat").pk]),
        {
            "starts_on": "2026-10-01",
            "fee_amount": "",
            "fee_frequency": "monthly",
            "vat_frequency": "quarterly",
            "vat_stagger": "1",
            "vat_scheme": "standard",
            "notes": "",
        },
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert (target.vat_frequency, target.vat_stagger) == ("quarterly", 1)
    assert target.deadlines.filter(rule="vat_return").exists()


def test_annual_accounting_needs_the_vat_year_end_month(client):
    target = company()
    sign_in(client, owner())
    response = client.post(
        reverse("services:switch_on", args=[target.pk, service("vat").pk]),
        {
            "starts_on": "2026-10-01",
            "fee_frequency": "monthly",
            "vat_frequency": "annual",
            "vat_scheme": "annual_accounting",
            "notes": "",
        },
    )
    assert response.status_code == 422
    assert not ClientService.objects.filter(client=target).exists()


def test_payroll_needs_the_pay_day_details(client):
    target = company()
    sign_in(client, owner())
    response = client.post(
        reverse("services:switch_on", args=[target.pk, service("payroll").pk]),
        {
            "starts_on": "2026-10-01",
            "fee_frequency": "monthly",
            "payroll_frequency": "monthly",
            "pay_day_rule": "day_of_month",
            "notes": "",
        },
    )
    assert response.status_code == 422
    assert "Enter the day of the month" in response.content.decode()


def test_a_renewal_service_asks_for_the_renewal_date(client):
    target = company()
    sign_in(client, owner())
    response = client.post(
        reverse("services:switch_on", args=[target.pk, service("registered_office").pk]),
        {
            "starts_on": "2026-10-01",
            "fee_frequency": "annual",
            "fee_amount": "60",
            "renewal_date": "2026-11-15",
            "notes": "",
        },
    )
    assert response.status_code == 302
    cs = ClientService.objects.get(client=target)
    assert (cs.settings["end_month"], cs.settings["end_day"], cs.settings["renewal"]) == (
        11,
        15,
        True,
    )


def test_switching_off_asks_for_an_end_date(client, world):
    sign_in(client, owner())
    url = reverse("services:switch_off", args=[world["client"].pk, world["cs"].pk])
    assert client.post(url, {}).status_code == 422
    response = client.post(url, {"ends_on": TODAY.isoformat(), "reason": "Deregistered"})
    assert response.status_code == 302
    world["cs"].refresh_from_db()
    assert world["cs"].state == "ended"


def test_a_prospect_gets_a_proposed_service_from_the_dialog(client):
    target = company(status="prospect")
    sign_in(client, owner())
    response = client.post(
        reverse("services:switch_on", args=[target.pk, service("bookkeeping").pk]),
        {
            "fee_frequency": "monthly",
            "frequency": "monthly",
            "end_month": "12",
            "due_days": "14",
            "notes": "",
        },
    )
    assert response.status_code == 302
    assert ClientService.objects.get(client=target).state == "proposed"


# ---------------------------------------------------------------- the Deadlines tab


def test_the_deadlines_tab_lists_open_ones_with_their_source_note(client, world):
    sign_in(client, staff())
    html = client.get(
        reverse("services:client_deadlines", args=[world["client"].pk])
    ).content.decode()
    assert world["deadline"].label in html
    assert "Calculated: one month and seven days after the period ends" in html
    assert "Not required" in html


def test_the_tab_has_its_own_link_on_the_client_page(client, world):
    sign_in(client, staff())
    html = client.get(reverse("clients:detail", args=[world["client"].pk])).content.decode()
    assert reverse("services:client_deadlines", args=[world["client"].pk]) in html


def test_a_client_with_no_services_gets_a_helpful_empty_state(client):
    target = company()
    sign_in(client, staff())
    html = client.get(reverse("services:client_deadlines", args=[target.pk])).content.decode()
    assert "No services yet" in html


def test_marking_a_deadline_done_from_the_tab(client, world):
    sign_in(client, staff())
    url = reverse("services:deadline_done", args=[world["client"].pk, world["deadline"].pk])
    response = client.post(url, {"done_on": TODAY.isoformat(), "note": "Filed"})
    assert response.status_code == 302
    world["deadline"].refresh_from_db()
    assert world["deadline"].status == "done"
    html = client.get(
        reverse("services:client_deadlines", args=[world["client"].pk])
    ).content.decode()
    assert "Past deadlines" in html


def test_changing_the_date_needs_a_reason(client, world):
    sign_in(client, staff())
    url = reverse("services:deadline_date", args=[world["client"].pk, world["deadline"].pk])
    response = client.post(url, {"due_date": "2027-01-01", "reason": ""})
    assert response.status_code == 422
    response = client.post(url, {"due_date": "2027-01-01", "reason": "HMRC extension"})
    assert response.status_code == 302
    world["deadline"].refresh_from_db()
    assert world["deadline"].due_date == date(2027, 1, 1)
    assert world["deadline"].original_due_date != date(2027, 1, 1)


def test_a_deadline_cannot_be_marked_done_in_the_future(client, world):
    sign_in(client, staff())
    url = reverse("services:deadline_done", args=[world["client"].pk, world["deadline"].pk])
    future = (TODAY + timedelta(days=3)).isoformat()
    assert client.post(url, {"done_on": future}).status_code == 422


# ---------------------------------------------------------------- the report


@pytest.fixture
def spread():
    """Open deadlines: one overdue, one in 10 days, one in 45 days, one in 80 days."""
    people = {"a": manager(), "b": manager()}
    clients = []
    for tag, offset, who in (
        ("Over", -5, "a"),
        ("Soon", 10, "a"),
        ("Mid", 45, "b"),
        ("Far", 80, "b"),
    ):
        c = ClientFactory(name=f"{tag} Ltd", manager=people[who])
        cs = take(c, "bookkeeping" if tag != "Far" else "vat")
        Deadline.objects.create(
            client=c,
            client_service=cs,
            rule="periodic" if tag != "Far" else "vat_return",
            period_key="x",
            label=f"{tag} deadline",
            due_date=TODAY + timedelta(days=offset),
            original_due_date=TODAY + timedelta(days=offset),
            source_note="Calculated: test",
        )
        clients.append(c)
    return {"people": people, "clients": clients}


def labels(response):
    return [d.label for d in response.context["page"].object_list]


def test_the_report_lists_open_deadlines_soonest_first(client, spread):
    sign_in(client, staff())
    response = client.get(reverse("services:report_deadlines"))
    assert labels(response) == ["Over deadline", "Soon deadline", "Mid deadline", "Far deadline"]


@pytest.mark.parametrize(
    ("within", "expected"),
    [
        ("14", ["Over deadline", "Soon deadline"]),
        ("30", ["Over deadline", "Soon deadline"]),
        ("60", ["Over deadline", "Soon deadline", "Mid deadline"]),
        ("90", ["Over deadline", "Soon deadline", "Mid deadline", "Far deadline"]),
    ],
)
def test_the_report_filters_by_how_soon(client, spread, within, expected):
    sign_in(client, staff())
    assert labels(client.get(reverse("services:report_deadlines"), {"within": within})) == expected


def test_the_report_filters_overdue_service_manager_and_client(client, spread):
    sign_in(client, staff())
    url = reverse("services:report_deadlines")
    assert labels(client.get(url, {"overdue": "on"})) == ["Over deadline"]
    assert labels(client.get(url, {"service": service("vat").pk})) == ["Far deadline"]
    assert labels(client.get(url, {"manager": spread["people"]["b"].pk})) == [
        "Mid deadline",
        "Far deadline",
    ]
    assert labels(client.get(url, {"client": "soon"})) == ["Soon deadline"]


def test_the_report_leaves_out_done_and_archived(client, spread):
    Deadline.objects.filter(label="Soon deadline").update(status="done")
    spread["clients"][2].archived_at = timezone.now()
    spread["clients"][2].save()
    sign_in(client, staff())
    assert labels(client.get(reverse("services:report_deadlines"))) == [
        "Over deadline",
        "Far deadline",
    ]


def test_the_export_needs_the_export_right_and_is_logged(client, spread):
    boss = owner()
    sign_in(client, boss)
    response = client.get(reverse("services:report_deadlines_export"), {"within": "14"})
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:3] == ["Client", "Reference", "Deadline"]
    assert [r[2] for r in rows[1:]] == ["Over deadline", "Soon deadline"]
    assert ActivityEvent.objects.filter(verb="export.run", data__list="deadlines").exists()


def test_the_export_makes_formula_text_safe(client):
    boss = owner()
    c = ClientFactory(name="=cmd Ltd")
    cs = take(c, "bookkeeping")
    Deadline.objects.create(
        client=c,
        client_service=cs,
        rule="periodic",
        period_key="x",
        label="+label",
        due_date=TODAY,
        original_due_date=TODAY,
    )
    sign_in(client, boss)
    body = client.get(reverse("services:report_deadlines_export")).content.decode()
    assert "'=cmd Ltd" in body
    assert "'+label" in body


# ---------------------------------------------------------------- the client list


def test_the_client_list_has_next_deadline_and_monthly_fee_columns(client, world):
    sign_in(client, owner())
    response = client.get(
        reverse("clients:list"), {"cols": ["name", "next_deadline", "monthly_fee"]}
    )
    html = response.content.decode()
    assert "Next deadline" in html and "Monthly fee" in html
    assert "£100.00" in html
    first = world["deadline"].due_date.strftime("%d/%m/%Y")
    assert first in html


def test_the_monthly_fee_column_is_hidden_without_the_right(client, world):
    role = Role.objects.create(slug="no-fees", name="No fees", rights=[])
    sign_in(client, UserFactory(role=role))
    html = client.get(reverse("clients:list"), {"cols": ["name", "monthly_fee"]}).content.decode()
    assert "Monthly fee" not in html
    assert "£100.00" not in html


def test_the_monthly_fee_sorts_and_exports_for_those_with_the_right(client, world):
    cheap = company(name="Cheap Ltd")
    take(cheap, "bookkeeping", fee_amount=Decimal("10.00"))
    sign_in(client, owner())
    page = client.get(
        reverse("clients:list"), {"cols": ["name", "monthly_fee"], "sort": "-monthly_fee"}
    )
    names = [c.name for c in page.context["page"].object_list]
    assert names.index(world["client"].name) < names.index("Cheap Ltd")
    export = client.get(reverse("clients:export"), {"cols": ["name", "monthly_fee"]})
    assert "100.00" in export.content.decode()


def test_the_list_filters_by_service_and_by_overdue(client, world):
    other = company(name="Other Ltd")
    take(other, "bookkeeping")
    overdue = company(name="Late Ltd")
    cs = take(overdue, "bookkeeping")
    Deadline.objects.create(
        client=overdue,
        client_service=cs,
        rule="periodic",
        period_key="late",
        label="Late",
        due_date=TODAY - timedelta(days=3),
        original_due_date=TODAY - timedelta(days=3),
    )
    sign_in(client, owner())
    url = reverse("clients:list")
    got = lambda params: {c.name for c in client.get(url, params).context["page"].object_list}  # noqa: E731
    assert got({"service": service("vat").pk}) == {world["client"].name}
    assert got({"service": service("bookkeeping").pk}) == {"Other Ltd", "Late Ltd"}
    Deadline.objects.filter(client=world["client"]).update(status="done")
    assert got({"overdue": "on"}) == {"Late Ltd"}


# ---------------------------------------------------------------- settings


def test_the_catalogue_page_lists_the_seeded_services(client):
    sign_in(client, owner())
    html = client.get(reverse("services:list")).content.decode()
    assert Service.objects.count() == 18
    assert "Fee Protection Service" in html
    assert "Operations and Controls Support" in html


def test_adding_and_editing_a_service(client):
    boss = owner()
    sign_in(client, boss)
    response = client.post(
        reverse("services:add"),
        {
            "name": "Budget Reviews",
            "kind": "advisory",
            "applies_to": ["ltd", "llp"],
            "rules": [],
        },
    )
    assert response.status_code == 302
    new = Service.objects.get(name="Budget Reviews")
    assert new.code == "budget-reviews"
    assert new.position > Service.objects.exclude(pk=new.pk).order_by("-position").first().position
    response = client.post(
        reverse("services:edit", args=[new.pk]),
        {
            "name": "Budget Reviews",
            "kind": "advisory",
            "applies_to": ["ltd"],
            "rules": ["periodic"],
            "active": "on",
            "default_fee": "250.00",
        },
    )
    assert response.status_code == 302
    new.refresh_from_db()
    assert new.rules == ["periodic"]
    assert new.default_fee == Decimal("250.00")
    assert new.code == "budget-reviews"  # the code is fixed once made
    assert ActivityEvent.objects.filter(verb="setting.changed").count() == 2


def test_service_names_must_be_unique(client):
    sign_in(client, owner())
    response = client.post(
        reverse("services:add"),
        {"name": "payroll", "kind": "compliance", "applies_to": ["ltd"], "rules": []},
    )
    assert response.status_code == 422


def test_reordering_and_switching_off_a_service(client):
    sign_in(client, owner())
    first, second = Service.objects.all()[:2]
    client.post(reverse("services:move", args=[second.pk, "up"]))
    assert list(Service.objects.all()[:2]) == [second, first]
    client.post(reverse("services:toggle", args=[first.pk]))
    first.refresh_from_db()
    assert first.active is False
    assert client.post(reverse("services:move", args=[first.pk, "sideways"])).status_code == 404


def test_a_switched_off_service_is_not_offered_to_a_client(client):
    sign_in(client, owner())
    off = service("training")
    off.active = False
    off.save()
    target = company()
    assert (
        "Training and Coaching"
        not in client.get(reverse("services:panel", args=[target.pk])).content.decode()
    )
    assert client.get(reverse("services:switch_on", args=[target.pk, off.pk])).status_code == 404


def test_services_on_the_service_object_use_the_services_function():
    # the catalogue helper that decides what a client is offered
    assert {s.code for s in services.applicable_services(company(client_type="partnership"))} >= {
        "partnership_return",
        "bookkeeping",
    }
