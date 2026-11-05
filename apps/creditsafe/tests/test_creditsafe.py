"""Creditsafe: report parsing, checks and history, drops, alerts and access."""

import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.creditsafe import api, services
from apps.creditsafe.fake import SAMPLES, FakeCreditsafe
from apps.creditsafe.models import CreditCheck
from apps.events.models import ActivityEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def on(settings):
    settings.CREDITSAFE_USERNAME = "made-up-user"
    settings.CREDITSAFE_PASSWORD = "made-up-password"
    settings.CREDITSAFE_PORTFOLIO_ID = "1"
    return settings


@pytest.fixture
def cl():
    return ClientFactory(name="Sample Trading Ltd", company_number="00000001")


def report(rating, score):
    data = json.loads((SAMPLES / "report.json").read_text())
    current = data["report"]["creditScore"]["currentCreditRating"]
    current["commonValue"], current["providerValue"]["value"] = rating, str(score)
    return data


def test_report_is_parsed():
    data = json.loads((SAMPLES / "report.json").read_text())
    assert api.parse_report(data) == {
        "connect_id": "GB-0-00000000",
        "score": 72,
        "rating": "B",
        "rating_description": "Low Risk",
        "credit_limit": Decimal("25000.00"),
        "currency": "GBP",
    }
    assert api.parse_report({})["score"] is None


def test_not_configured_is_explained(cl):
    with pytest.raises(ValidationError, match="not set up"):
        services.check_client(owner(), cl, transport=FakeCreditsafe())


def test_check_stores_history_logs_and_monitors(on, cl):
    fake = FakeCreditsafe()
    check = services.check_client(owner(), cl, transport=fake)
    assert (check.rating, check.score, check.connect_id) == ("B", 72, "GB-0-00000001")
    assert ActivityEvent.objects.filter(verb="credit.checked", client=cl).exists()
    assert any("monitoring/portfolios" in r["path"] for r in fake.requests)
    assert "made-up-password" not in repr(api.Creditsafe(fake))


def test_a_company_number_is_needed(on):
    with pytest.raises(ValidationError, match="company number"):
        services.check_client(owner(), ClientFactory(company_number=""), transport=FakeCreditsafe())


def test_unknown_company(on):
    with pytest.raises(ValidationError, match="no company"):
        services.check_client(
            owner(), ClientFactory(company_number="00000404"), transport=FakeCreditsafe()
        )


def test_a_drop_notifies_the_owner_and_shows_on_overview(on, cl):
    boss = owner()
    fake = FakeCreditsafe()
    services.check_client(boss, cl, transport=fake)
    fake.reports["GB-0-00000001"] = report("D", 30)
    services.check_client(boss, cl, transport=fake)
    assert boss.notifications.filter(message__contains="fell from B to D").exists()
    drops = services.recent_drops()
    assert [d["client"] for d in drops] == [cl]


def test_alerts_recheck_only_named_companies(on, cl):
    fake = FakeCreditsafe()
    services.check_client(owner(), cl, transport=fake)
    other = ClientFactory(company_number="00000002")
    services.check_client(owner(), other, transport=fake)
    fake.reports["GB-0-00000001"] = report("C", 50)
    result = services.run_alerts(transport=fake)
    assert result == {"alerts": 1, "rechecked": 1}
    assert cl.credit_checks.first().source == CreditCheck.Source.ALERT
    assert other.credit_checks.count() == 1
    assert services.run_alerts(transport=fake)["rechecked"] == 1  # same event date: kept


def test_alerts_do_nothing_until_set_up():
    assert services.run_alerts() == {"skipped": "not configured"}


def test_check_button_needs_the_right(client, cl):
    url = reverse("creditsafe:check", args=[cl.pk])
    assert client.post(url).status_code == 302 and "/login/" in client.post(url)["Location"]
    for who in (staff, portal_user):
        sign_in(client, who())
        assert client.post(url).status_code == 403
        client.logout()
    sign_in(client, manager())
    assert client.post(url).status_code == 302  # not set up: message, no report
    assert not CreditCheck.objects.exists()


def test_risk_tab_and_header_show_the_rating(client, cl):
    CreditCheck.objects.create(client=cl, company_number=cl.company_number, rating="B", score=72)
    sign_in(client, owner())
    page = client.get(reverse("aml:tab", args=[cl.pk])).content.decode()
    assert "Credit rating" in page and "Credit B" in page
