from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role
from apps.accounts.tests.factories import owner, staff
from apps.events.models import ActivityEvent
from apps.services import fees, services
from apps.services.models import ClientService, FeeChange

from .factories import company, service

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("amount", "frequency", "expected"),
    [
        ("100.00", "monthly", "100.00"),
        ("100.00", "quarterly", "33.33"),
        ("200.00", "quarterly", "66.67"),  # 66.666... rounds half up
        ("100.00", "annual", "8.33"),
        ("150.00", "annual", "12.50"),
        ("0.06", "annual", "0.01"),  # 0.005 rounds half up
        ("500.00", "one_off", "0.00"),
    ],
)
def test_monthly_equivalent_rounds_half_up_to_pence(amount, frequency, expected):
    assert fees.monthly_equivalent(Decimal(amount), frequency) == Decimal(expected)


def test_no_fee_has_no_monthly_equivalent():
    assert fees.monthly_equivalent(None, "monthly") is None


def test_totals_round_each_service_before_adding_and_keep_one_off_separate():
    rows = [
        ClientService(fee_amount=Decimal("100.00"), fee_frequency="quarterly"),
        ClientService(fee_amount=Decimal("100.00"), fee_frequency="quarterly"),
        ClientService(fee_amount=Decimal("250.00"), fee_frequency="monthly"),
        ClientService(fee_amount=Decimal("400.00"), fee_frequency="one_off"),
        ClientService(fee_amount=None, fee_frequency="monthly"),
    ]
    monthly, one_off = fees.totals(rows)
    assert monthly == Decimal("316.66")  # 33.33 + 33.33 + 250.00, not 66.67 + 250.00
    assert one_off == Decimal("400.00")


def test_switching_on_with_a_fee_logs_the_first_fee_change():
    boss = owner()
    client = company()
    cs = services.switch_on(boss, client, service("bookkeeping"), fee_amount=Decimal("120.00"))
    change = FeeChange.objects.get(client_service=cs)
    assert (change.old_amount, change.new_amount, change.changed_by) == (
        None,
        Decimal("120.00"),
        boss,
    )
    assert cs.state == "active"
    assert cs.starts_on is not None


def test_every_fee_change_writes_a_row_and_an_event():
    boss = owner()
    client = company()
    cs = services.switch_on(boss, client, service("bookkeeping"), fee_amount=Decimal("120.00"))
    services.change_fee(boss, cs, Decimal("150.00"), "monthly", reason="Annual review")
    services.change_fee(boss, cs, Decimal("1800.00"), "annual", reason="Moved to annual")
    rows = list(FeeChange.objects.filter(client_service=cs).order_by("id"))
    assert [(r.old_amount, r.new_amount, r.old_frequency, r.new_frequency) for r in rows] == [
        (None, Decimal("120.00"), "", "monthly"),
        (Decimal("120.00"), Decimal("150.00"), "monthly", "monthly"),
        (Decimal("150.00"), Decimal("1800.00"), "monthly", "annual"),
    ]
    assert rows[1].reason == "Annual review"
    assert ActivityEvent.objects.filter(verb="service.fee_changed", client=client).count() == 2


def test_saving_the_same_fee_writes_nothing():
    boss = owner()
    cs = services.switch_on(boss, company(), service("bookkeeping"), fee_amount=Decimal("120.00"))
    services.change_fee(boss, cs, Decimal("120.00"), "monthly")
    assert FeeChange.objects.filter(client_service=cs).count() == 1


def test_changing_a_fee_needs_the_fees_right():
    boss = owner()
    cs = services.switch_on(boss, company(), service("bookkeeping"), fee_amount=Decimal("120.00"))
    nobody = staff()
    nobody.role = Role.objects.create(slug="no-fees", name="No fees")
    nobody.save()
    with pytest.raises(PermissionDenied):
        services.change_fee(nobody, cs, Decimal("1.00"), "monthly")


def test_a_service_must_apply_to_the_client_type():
    boss = owner()
    sole = company(client_type="sole_trader")
    with pytest.raises(ValidationError):
        services.switch_on(boss, sole, service("accounts"))  # companies and LLPs only


def test_a_service_cannot_be_on_twice_but_can_start_again_after_it_ended():
    from datetime import date

    boss = owner()
    client = company()
    cs = services.switch_on(boss, client, service("bookkeeping"))
    with pytest.raises(ValidationError):
        services.switch_on(boss, client, service("bookkeeping"))
    services.end_service(boss, cs, date(2026, 10, 1))
    again = services.switch_on(boss, client, service("bookkeeping"))
    assert again.pk != cs.pk


def test_a_prospect_gets_a_proposed_service():
    boss = owner()
    client = company(status="prospect")
    cs = services.switch_on(boss, client, service("bookkeeping"), fee_amount=Decimal("90.00"))
    assert cs.state == "proposed"


def test_a_former_client_cannot_take_a_service():
    boss = owner()
    with pytest.raises(ValidationError):
        services.switch_on(boss, company(status="former"), service("bookkeeping"))


def test_the_default_fee_is_used_when_the_service_has_one():
    boss = owner()
    catalogue = service("bookkeeping")
    catalogue.default_fee = Decimal("75.00")
    catalogue.save()
    cs = services.switch_on(boss, company(), catalogue)
    assert cs.fee_amount == Decimal("75.00")
