from datetime import date

import pytest

from apps.core import dates
from apps.core import jobs as core_jobs
from apps.core.models import StoredBankHolidays
from apps.jobs.services import run_job

pytestmark = pytest.mark.django_db

# The shape gov.uk publishes. Dates for a made-up year so nothing real is relied on.
SAMPLE = {
    "england-and-wales": {
        "division": "england-and-wales",
        "events": [
            {"title": f"Holiday {n}", "date": f"2031-{m:02d}-{d:02d}", "notes": "", "bunting": True}
            for n, (m, d) in enumerate(
                [(1, 1), (4, 11), (4, 14), (5, 5), (5, 26), (8, 25), (12, 25), (12, 26), (6, 2)]
            )
        ],
    },
    "scotland": {"division": "scotland", "events": [{"title": "X", "date": "2031-01-02"}]},
}


@pytest.fixture(autouse=True)
def _fresh(settings):
    settings.BANK_HOLIDAYS_FROM_DATABASE = True
    dates.clear_bank_holiday_cache()
    yield
    dates.clear_bank_holiday_cache()


def test_the_refresh_stores_england_and_wales_dates(monkeypatch):
    monkeypatch.setattr(core_jobs, "fetch_gov_uk", lambda: SAMPLE)
    run = run_job("bank_holidays")
    assert run.state == "done"
    assert run.counts == {"dates": 9, "changed": 9}
    row = StoredBankHolidays.objects.get()
    assert "2031-06-02" in row.dates and "2031-01-02" not in row.dates
    assert date(2031, 6, 2) in dates.bank_holidays()
    assert not dates.is_working_day(date(2031, 6, 2))
    # Years gov.uk did not send keep the bundled dates.
    assert date(2026, 12, 25) in dates.bank_holidays()


def test_the_refresh_fails_quietly(monkeypatch):
    from apps.accounts.tests.factories import owner
    from apps.events.models import Notification

    boss = owner()

    def broken():
        raise OSError("blocked")

    monkeypatch.setattr(core_jobs, "fetch_gov_uk", broken)
    run = run_job("bank_holidays")
    assert run.state == "done"
    assert "stays in use" in run.message
    assert not StoredBankHolidays.objects.exists()
    assert not Notification.objects.filter(user=boss).exists()
    assert date(2026, 12, 25) in dates.bank_holidays()


def test_a_wrong_shape_changes_nothing(monkeypatch):
    StoredBankHolidays.objects.create(dates=["2031-06-02"])
    monkeypatch.setattr(core_jobs, "fetch_gov_uk", lambda: {"england-and-wales": {"events": []}})
    run_job("bank_holidays")
    assert StoredBankHolidays.objects.get().dates == ["2031-06-02"]


def test_stored_years_replace_bundled_years():
    bundled = frozenset({date(2030, 1, 1), date(2030, 5, 6), date(2029, 1, 1)})
    merged = dates.merge_bank_holidays(bundled, ["2030-01-01", "2030-05-13"])
    assert merged == {date(2030, 1, 1), date(2030, 5, 13), date(2029, 1, 1)}
