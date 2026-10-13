"""Date helpers against the cases in docs/specs/03-services-and-deadlines.md section 6.

Never change an expected date to make a test pass.
"""

from datetime import date

import pytest

from apps.core import dates


def d(text: str) -> date:
    day, month, year = (int(part) for part in text.split("/"))
    return date(year, month, day)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("31/03/2026", 9, "31/12/2026"),
        ("28/02/2026", 9, "30/11/2026"),
        ("30/04/2026", 9, "31/01/2027"),
        ("30/09/2026", 9, "30/06/2027"),
        ("31/05/2026", 9, "28/02/2027"),
        ("15/08/2026", 9, "15/05/2027"),
        ("29/02/2028", 12, "28/02/2029"),
    ],
)
def test_add_months_month_end_rule(start, months, expected):
    assert dates.add_months(d(start), months) == d(expected)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("31/12/2026", -9, "31/03/2026"),
        ("15/05/2027", -9, "15/08/2026"),
        ("31/01/2026", 1, "28/02/2026"),
        ("15/01/2026", 0, "15/01/2026"),
        ("30/11/2026", 3, "28/02/2027"),
    ],
)
def test_add_months_other_cases(start, months, expected):
    assert dates.add_months(d(start), months) == d(expected)


@pytest.mark.parametrize(
    ("period_end", "return_due"),
    [
        ("31/03/2026", "31/03/2027"),
        ("28/02/2026", "28/02/2027"),
        ("30/06/2026", "30/06/2027"),
        ("29/02/2028", "28/02/2029"),
    ],
)
def test_ct600_return_due_is_twelve_months_after(period_end, return_due):
    assert dates.add_months(d(period_end), 12) == d(return_due)


@pytest.mark.parametrize(
    ("period_end", "payment_due"),
    [
        # HMRC's own examples (CTM01800)
        ("31/03/1999", "01/01/2000"),
        ("01/07/1999", "02/04/2000"),
        ("28/02/2000", "29/11/2000"),
        ("29/02/2000", "01/12/2000"),
        ("28/05/2000", "01/03/2001"),
        ("29/05/2000", "01/03/2001"),
        ("30/05/2000", "01/03/2001"),
        ("31/05/2000", "01/03/2001"),
        # Further cases from the spec
        ("31/03/2026", "01/01/2027"),
        ("28/02/2026", "01/12/2026"),
        ("30/06/2026", "01/04/2027"),
        ("30/09/2026", "01/07/2027"),
        ("15/08/2026", "16/05/2027"),
        ("29/02/2028", "01/12/2028"),
    ],
)
def test_ct_payment_due(period_end, payment_due):
    assert dates.ct_payment_due(d(period_end)) == d(payment_due)


def test_ct_payment_for_the_long_period_example():
    # Long accounts period 01/01/2025 to 31/03/2026: two tax periods.
    assert dates.ct_payment_due(d("31/12/2025")) == d("01/10/2026")
    assert dates.ct_payment_due(d("31/03/2026")) == d("01/01/2027")


@pytest.mark.parametrize(
    ("period_end", "due"),
    [
        ("30/09/2026", "07/11/2026"),
        ("31/10/2026", "07/12/2026"),
        ("30/11/2026", "07/01/2027"),
        ("31/12/2026", "07/02/2027"),
        ("31/01/2027", "07/03/2027"),
        ("28/02/2027", "07/04/2027"),
    ],
)
def test_vat_due(period_end, due):
    assert dates.vat_due(d(period_end)) == d(due)


def test_vat_due_for_a_period_not_ending_on_a_month_end():
    assert dates.vat_due(d("15/08/2026")) == d("22/09/2026")


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("07/11/2026", "06/11/2026"),  # Saturday
        ("22/11/2026", "20/11/2026"),  # Sunday
        ("25/12/2026", "24/12/2026"),  # bank holiday
        ("31/08/2026", "28/08/2026"),  # bank holiday
        ("31/12/2026", "31/12/2026"),  # Thursday
    ],
)
def test_previous_working_day_on_or_before(day, expected):
    assert dates.previous_working_day(d(day)) == d(expected)


@pytest.mark.parametrize(
    ("day", "working"),
    [
        ("12/10/2026", True),  # Monday
        ("10/10/2026", False),  # Saturday
        ("11/10/2026", False),  # Sunday
        ("03/04/2026", False),  # Good Friday
        ("28/12/2026", False),  # substitute Boxing Day
        ("26/03/2027", False),  # Good Friday 2027
        ("03/01/2028", False),  # substitute New Year's Day
        ("29/12/2026", True),
    ],
)
def test_is_working_day(day, working):
    assert dates.is_working_day(d(day)) is working


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        ("23/12/2026", 1, "24/12/2026"),
        ("24/12/2026", 1, "29/12/2026"),  # over Christmas, a weekend and two bank holidays
        ("29/12/2026", -1, "24/12/2026"),
        ("30/10/2026", 2, "03/11/2026"),
        ("03/11/2026", -2, "30/10/2026"),
        ("10/10/2026", 0, "10/10/2026"),
        ("02/04/2026", 1, "07/04/2026"),  # Easter 2026
    ],
)
def test_add_working_days(start, n, expected):
    assert dates.add_working_days(d(start), n) == d(expected)


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2026, 8, "28/08/2026"),  # the 31st is a bank holiday
        (2026, 10, "30/10/2026"),
        (2026, 12, "31/12/2026"),
    ],
)
def test_last_working_day_of_month(year, month, expected):
    assert dates.last_working_day_of_month(year, month) == d(expected)


def test_monthly_pay_on_the_25th_moves_to_the_working_day_before():
    assert dates.previous_working_day(d("25/10/2026")) == d("23/10/2026")  # Sunday
    assert dates.previous_working_day(d("25/12/2026")) == d("24/12/2026")  # bank holiday


def test_paye_pay_by_hint_for_a_weekend_due_date():
    # PAYE for the tax month ending 05/11/2026 is due 22/11/2026, a Sunday.
    assert dates.previous_working_day(d("22/11/2026")) == d("20/11/2026")


@pytest.mark.parametrize(
    ("day", "end", "label"),
    [
        ("05/04/2026", "05/04/2026", "2025/26"),
        ("06/04/2026", "05/04/2027", "2026/27"),
        ("31/12/2026", "05/04/2027", "2026/27"),
        ("01/01/2000", "05/04/2000", "1999/00"),
        ("06/04/2009", "05/04/2010", "2009/10"),
    ],
)
def test_tax_year(day, end, label):
    assert dates.tax_year_of(d(day)) == d(end)
    assert dates.tax_year_label(d(end)) == label
    assert dates.tax_year_label(d(end).year) == label


def test_tax_year_start():
    assert dates.tax_year_start(d("05/04/2027")) == d("06/04/2026")


def test_bundled_bank_holidays_match_the_spec():
    holidays = dates.bank_holidays()
    assert len(holidays) == 24
    assert {h.year for h in holidays} == {2026, 2027, 2028}
    for text in ["01/01/2026", "06/04/2026", "28/12/2026", "29/03/2027", "26/12/2028"]:
        assert d(text) in holidays
