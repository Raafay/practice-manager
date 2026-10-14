"""The worked example in docs/specs/09-time-fees-forecast.md section 6, every figure."""

from datetime import date
from decimal import Decimal

import pytest

from apps.clients.models import Client
from apps.clients.tests.factories import ClientFactory
from apps.finance import forecast
from apps.finance.models import FinanceSettings, Target
from apps.finance.tests.helpers import (
    decided,
    give_service,
    live_client,
    prospect,
    sent_proposal,
)
from apps.pipeline import services as pipeline_services

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 12)
NOV, DEC = date(2026, 11, 1), date(2026, 12, 1)


def D(value):
    return Decimal(value)


@pytest.fixture
def world():
    live_client("Client A", "accounts", 300, since=date(2026, 3, 1))
    live_client("Client B", "payroll", 450, since=date(2026, 6, 15), ends=date(2026, 11, 30))
    live_client("Client C", "accounts", 1200, "quarterly", since=date(2023, 1, 1))
    live_client("Client D", "self_assessment", 2400, "annual", since=date(2022, 1, 1))
    e = ClientFactory(name="Client E", status=Client.Status.ONBOARDING)
    give_service(e, "accounts", 350, state="proposed")
    details = pipeline_services.ensure_details(e)
    details.expected_start, details.setup_fee = NOV, D("150")
    details.save()
    f = prospect("Prospect F", 500, "proposal_sent", start=NOV)
    prospect("Prospect G", 250, "meeting_held", start=DEC)
    prospect("Prospect H", 400, "on_hold")
    sent_proposal(f, 500, date(2026, 9, 20))
    # Client A and B were made live in the last year; E is not live. Six won, four lost: A and B
    # count as two of the won, so four more are added.
    decided(6, 4, TODAY)
    Target.objects.create(month=NOV, amount=D("3000"))
    Target.objects.create(month=DEC, amount=D("3000"))
    FinanceSettings.load()


def figures(month):
    snap = forecast.gather(TODAY, 60)
    targets = forecast.target_map()
    row = forecast.month_row(snap, targets, month)
    return snap, row, forecast.feedback(snap, row, today=TODAY)


def test_contracted_today(world):
    assert forecast.contracted_now(forecast.gather(TODAY, 60)) == D("1350.00")


@pytest.mark.parametrize(
    "month, contracted, weighted, total, gap, one_off",
    [
        (NOV, "1700.00", "300.00", "2000.00", "1000.00", "150.00"),
        (DEC, "1250.00", "407.50", "1657.50", "1342.50", "0.00"),
    ],
)
def test_month_figures(world, month, contracted, weighted, total, gap, one_off):
    _, row, _ = figures(month)
    assert row.contracted == D(contracted)
    assert row.weighted == D(weighted)
    assert row.forecast == D(total)
    assert row.gap == D(gap)
    assert row.one_off == D(one_off)


@pytest.mark.parametrize("month, clients, proposals", [(NOV, 3, 5), (DEC, 4, 7)])
def test_feedback_figures(world, month, clients, proposals):
    _, _, fb = figures(month)
    assert fb.figures["average_fee"] == D("375.00")
    assert fb.figures["win_rate"] == 60
    assert fb.figures["clients_needed"] == clients
    assert fb.figures["proposals_needed"] == proposals
    assert fb.figures["waiting"] == D("500.00")


def test_feedback_lines_in_order(world):
    _, _, fb = figures(NOV)
    assert fb.lines[0] == "You are £1,000.00 a month short of your target for November 2026."
    assert fb.lines[1] == (
        "At your average new-client fee of £375.00 a month, that is 3 more clients."
    )
    assert fb.lines[2] == "At your win rate of 60%, that means about 5 more proposals."
    assert fb.lines[3].startswith("£500.00 a month of proposals are waiting for an answer.")
    assert "1 of them have had no contact for 14 days or more." in fb.lines[3]
    assert len(fb.lines) == 4  # nothing ends before November; no time logged


def test_ending_line_for_december(world):
    _, _, fb = figures(DEC)
    assert (
        "£450.00 a month is due to end by December 2026 from clients leaving or reducing."
        in fb.lines
    )


def test_ahead_of_target_wording_and_no_client_lines(world):
    Target.objects.filter(month=NOV).update(amount=D("1500"))
    _, row, fb = figures(NOV)
    assert fb.lines[0] == "You are £500.00 a month ahead of your target for November 2026."
    assert not any("more client" in line for line in fb.lines)


def test_win_rate_hidden_below_five_decided():
    live_client("Only", "accounts", 100, since=date(2026, 5, 1))
    decided(2, 2, TODAY)
    Target.objects.create(month=NOV, amount=D("1000"))
    _, _, fb = figures(NOV)
    assert fb.figures["win_rate"] is None
    assert not any("win rate" in line for line in fb.lines)


def test_average_fee_falls_back_to_all_live_clients():
    live_client("Old One", "accounts", 200, since=date(2020, 1, 1))
    live_client("Old Two", "vat", 300, since=date(2019, 1, 1))
    assert forecast.average_new_client_fee(TODAY) == D("250.00")


def test_no_fee_paying_clients_hides_lines():
    Target.objects.create(month=NOV, amount=D("1000"))
    _, _, fb = figures(NOV)
    assert fb.figures["average_fee"] is None
    assert not any("average new-client fee" in line for line in fb.lines)


def test_no_target_means_no_gap_lines():
    live_client("Solo", "accounts", 100, since=date(2026, 5, 1))
    _, row, fb = figures(NOV)
    assert row.gap is None
    assert not any("target" in line for line in fb.lines)


# ---------------------------------------------------------------- the rules behind the sums


def test_service_starting_mid_month_counts_that_month():
    client = ClientFactory()
    give_service(client, "accounts", 100, starts=date(2026, 11, 20))
    snap = forecast.gather(TODAY, 60)
    assert forecast.contracted(snap, date(2026, 10, 1)) == D("0.00")
    assert forecast.contracted(snap, NOV) == D("100.00")


def test_service_ending_mid_month_does_not_count_that_month():
    client = ClientFactory()
    give_service(client, "accounts", 100, ends=date(2026, 11, 29))
    snap = forecast.gather(TODAY, 60)
    assert forecast.contracted(snap, date(2026, 10, 1)) == D("100.00")
    assert forecast.contracted(snap, NOV) == D("0.00")


def test_service_ending_on_the_last_day_counts_that_month():
    client = ClientFactory()
    give_service(client, "accounts", 100, ends=date(2026, 11, 30))
    assert forecast.contracted(forecast.gather(TODAY, 60), NOV) == D("100.00")


def test_monthly_equivalents_round_each_service_before_adding():
    one = ClientFactory()
    give_service(one, "accounts", "100.00", "quarterly")  # 33.33
    two = ClientFactory()
    give_service(two, "vat", "100.00", "quarterly")  # 33.33
    assert forecast.contracted(forecast.gather(TODAY, 60), NOV) == D("66.66")


def test_one_off_services_are_not_recurring():
    client = ClientFactory()
    give_service(client, "accounts", 500, "one_off", starts=date(2026, 11, 5))
    snap = forecast.gather(TODAY, 60)
    assert forecast.contracted(snap, NOV) == D("0.00")
    assert forecast.one_off_income(snap, NOV) == D("500.00")


def test_former_clients_do_not_count():
    live_client("Gone", "accounts", 100, since=date(2020, 1, 1))
    Client.objects.filter(name="Gone").update(status=Client.Status.FORMER)
    assert forecast.contracted(forecast.gather(TODAY, 60), NOV) == D("0.00")


def test_a_prospect_with_no_start_uses_the_setting():
    prospect("Late", 1000, "enquiry")  # 10%
    assert forecast.weighted_pipeline(forecast.gather(TODAY, 60), NOV) == D("0.00")
    assert forecast.weighted_pipeline(forecast.gather(TODAY, 60), DEC) == D("100.00")
    assert forecast.weighted_pipeline(forecast.gather(TODAY, 10), NOV) == D("100.00")
    assert forecast.weighted_pipeline(forecast.gather(TODAY, 10), date(2026, 10, 1)) == D("100.00")


def test_lost_and_won_prospects_are_not_pipeline():
    prospect("Won one", 1000, "won", start=NOV)
    prospect("Lost one", 1000, "lost", start=NOV)
    assert forecast.weighted_pipeline(forecast.gather(TODAY, 60), NOV) == D("0.00")


def test_close_to_full_line():
    from apps.accounts.tests.factories import staff
    from apps.timekeeping import services as time_services

    person = staff(weekly_hours=Decimal("40"))
    live_client("Busy", "accounts", 100, since=date(2026, 5, 1))
    Target.objects.create(month=NOV, amount=D("1000"))
    # September 2026 has 22 working days: 176 hours available for one 40 hour person.
    for day in range(1, 22):  # 21 days of 8 hours plus 4 hours
        time_services.log_time(person, minutes=8 * 60, on_date=date(2026, 9, day))
    time_services.log_time(person, minutes=4 * 60, on_date=date(2026, 9, 22))
    _, _, fb = figures(NOV)
    line = next(line for line in fb.lines if line.startswith("The team logged"))
    assert "172.0 hours last month against 176.0 hours available." in line
    assert "You are close to full." in line
