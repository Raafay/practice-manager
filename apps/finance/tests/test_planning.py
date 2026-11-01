"""Profit planning, the Xero profit and loss report, the Profit page and the assistant."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.finance import assistant, planning, sync
from apps.finance.models import AssistantMessage, MonthlyResult, ProfitTarget
from apps.services.tests.factories import company, take

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 1)


def results(costs=Decimal("9000")):
    for month in (date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)):
        MonthlyResult.objects.create(
            month=month, income=Decimal("14000"), overheads=costs, net_profit=14000 - costs
        )


def fees(*amounts):
    for amount in amounts:
        take(company(), "bookkeeping", fee_amount=Decimal(amount), fee_frequency="monthly")


def test_xero_profit_and_loss_report_is_read_by_month():
    import json

    from apps.finance.xero_fake import SAMPLES

    data = json.loads((SAMPLES / "profit_and_loss.json").read_text())
    found = sync.parse_profit_and_loss(data)
    assert found[date(2026, 9, 1)] == {
        "income": Decimal("14000.00"),
        "cost_of_sales": Decimal("1200.00"),
        "overheads": Decimal("7800.00"),
        "net_profit": Decimal("5000.00"),
    }
    assert set(found) == {date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)}
    assert sync.store_profit_and_loss(data) == 3
    assert sync.store_profit_and_loss(data) == 3  # safe twice
    assert MonthlyResult.objects.count() == 3


def test_position_gives_gap_and_clients_needed():
    fees("3000", "3000", "3000", "3000")  # £12,000 a month, average fee £3,000
    results(Decimal("9000"))
    pos = planning.position(Decimal("8000"), today=TODAY)
    assert pos["monthly_fees_now"] == "12000.00"
    assert pos["monthly_costs_run_rate"] == "9000.00"
    assert pos["monthly_profit_now"] == "3000.00"
    assert pos["margin_percent_now"] == "25.0"
    assert pos["gap_to_target"] == "5000.00"
    assert pos["clients_needed"] == 2  # 5000 / 3000 rounded up


def test_position_uses_the_saved_profit_target():
    fees("1000")
    results(Decimal("500"))
    ProfitTarget.objects.create(month=date(2026, 11, 1), profit=Decimal("600"))
    assert planning.position(today=TODAY)["target_profit"] == "600.00"


def test_no_profit_and_loss_says_so():
    fees("1000")
    pos = planning.position(Decimal("8000"), today=TODAY)
    assert pos["monthly_profit_now"] is None and pos["clients_needed"] is None
    assert pos["notes"]


def test_scenario_four_new_clients_at_350():
    fees("2000", "2000")
    results(Decimal("3000"))
    s = planning.scenario(4, Decimal("350"), today=TODAY)
    assert s["added_monthly_fees"] == "1400.00"
    assert s["monthly_profit_before"] == "1000.00"
    assert s["monthly_profit_after"] == "2400.00"
    with pytest.raises(ValueError):
        planning.scenario(-1)


def test_concentration_warns_above_a_quarter():
    fees("4000", "1000", "1000", "1000", "1000", "1000", "1000")
    data = planning.concentration()
    assert data["clients"][0]["share_percent"] == "40.0"
    assert len(data["warnings"]) == 1


def test_people_are_not_named_to_the_assistant():
    from apps.clients.tests.factories import ClientFactory

    person = ClientFactory(client_type="individual", name="Made Up Person")
    assert "Made Up Person" not in planning.client_label(person)


def test_forecast_against_actual_has_targets_and_actuals():
    results()
    ProfitTarget.objects.create(month=date(2026, 9, 1), profit=Decimal("5000"))
    rows = {r["month"]: r for r in planning.forecast_against_actual(today=TODAY)}
    assert rows["09/2026"]["actual_profit"] == "5000.00"
    assert rows["09/2026"]["target_profit"] == "5000.00"
    assert rows["12/2026"]["actual_profit"] is None


# ---------------------------------------------------------------- the assistant


class FakeClaude:
    """Answers with one tool call, then a text answer. Records what it was sent."""

    def __init__(self, tool="get_position", args=None):
        self.sent = []
        self.replies = [
            SimpleNamespace(
                stop_reason="tool_use",
                model="claude-opus-5-5",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=50),
                content=[SimpleNamespace(type="tool_use", id="t1", name=tool, input=args or {})],
            ),
            SimpleNamespace(
                stop_reason="end_turn",
                model="claude-opus-5-5",
                usage=SimpleNamespace(input_tokens=1200, output_tokens=200),
                content=[SimpleNamespace(type="text", text="You need 2 more clients.")],
            ),
        ]
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.sent.append(kwargs)
        return self.replies.pop(0)


def test_assistant_calls_our_functions_and_meters_usage():
    fees("3000")
    results(Decimal("2000"))
    fake = FakeClaude(args={"target_profit": 8000})
    user = owner()
    record = assistant.ask(user, "I want £8k profit a month", client=fake)
    assert record.answer == "You need 2 more clients."
    assert record.tools_used == [{"name": "get_position", "input": {"target_profit": 8000}}]
    assert (record.input_tokens, record.output_tokens, record.calls) == (2200, 250, 2)
    tool_result = fake.sent[1]["messages"][-1]["content"][0]
    assert '"gap_to_target": "7000.00"' in tool_result["content"]
    assert fake.sent[0]["model"] == "claude-opus-5-5"
    assert assistant.cost_dollars(record) > 0


def test_assistant_bad_tool_input_is_returned_as_an_error():
    fake = FakeClaude(tool="run_scenario", args={"new_clients": 9999})
    assistant.ask(owner(), "What if?", client=fake)
    assert fake.sent[1]["messages"][-1]["content"][0]["is_error"] is True


def test_unknown_tool_is_refused():
    with pytest.raises(ValueError):
        assistant.run_tool("delete_everything", {})


def test_assistant_api_failure_is_saved_and_explained():
    import anthropic

    class Broken:
        beta = SimpleNamespace(
            messages=SimpleNamespace(
                create=lambda **k: (_ for _ in ()).throw(
                    anthropic.APIConnectionError(request=SimpleNamespace(url="x"))
                )
            )
        )

    record = assistant.ask(owner(), "Hello", client=Broken())
    assert record.failed and "not available" in record.answer


# ---------------------------------------------------------------- pages


@pytest.mark.parametrize("name", ["finance:profit", "finance:assistant"])
def test_pages_are_owner_only(client, name):
    url = reverse(name)
    assert client.get(url).status_code == 302
    for who in (staff, manager, portal_user):
        sign_in(client, who())
        assert client.get(url).status_code == 403, who
        client.logout()
    sign_in(client, owner())
    assert client.get(url).status_code == 200


def test_profit_page_shows_scenario_and_saves_targets_and_months(client):
    sign_in(client, owner())
    html = client.get(reverse("finance:profit") + "?clients=4&fee=350").content.decode()
    assert "Added fees" in html
    client.post(
        reverse("finance:profit"), {"action": "target", "month": "2026-12", "profit": "8000"}
    )
    assert ProfitTarget.objects.get().profit == Decimal("8000")
    client.post(
        reverse("finance:profit"),
        {"action": "result", "month": "2026-09", "income": "100", "overheads": "40"},
    )
    assert MonthlyResult.objects.get().net_profit == Decimal("60")


def test_assistant_page_without_a_key_says_so(client):
    sign_in(client, owner())
    assert "not set up" in client.get(reverse("finance:assistant")).content.decode()
    client.post(reverse("finance:assistant"), {"question": "Hi"})
    assert not AssistantMessage.objects.exists()


def test_assistant_page_runs_a_question(client, settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "test-key-not-real"
    monkeypatch.setattr(assistant, "make_client", lambda: FakeClaude())
    user = owner()
    sign_in(client, user)
    response = client.post(reverse("finance:assistant"), {"question": "How are we doing?"})
    record = AssistantMessage.objects.get()
    assert response["Location"].endswith(f"?c={record.conversation}")
    page = client.get(response["Location"]).content.decode()
    assert "You need 2 more clients." in page
    # Another owner cannot read this conversation.
    other = owner()
    client.logout()
    sign_in(client, other)
    assert "You need 2 more clients." not in client.get(response["Location"]).content.decode()
