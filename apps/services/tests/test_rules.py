"""Table-driven tests for the deadline rules: the cases come from docs/specs/03 section 6.

Expected values are exactly as the spec gives them. They are never changed to pass.
"""

from datetime import date

import pytest

from apps.core import dates
from apps.services.rules import REGISTRY, Inputs


def d(text: str) -> date:
    day, month, year = text.split("/")
    return date(int(year), int(month), int(day))


def run(name: str, today: str, **kwargs):
    return REGISTRY[name].func(Inputs(today=d(today), **kwargs))


def by_key(periods):
    return {p.key: p for p in periods}


def test_all_seventeen_rules_are_registered():
    assert set(REGISTRY) == {
        "ch_accounts",
        "ct600",
        "ct_payment",
        "confirmation_statement",
        "vat_return",
        "payroll_run",
        "paye_payment",
        "payroll_year_end",
        "p11d",
        "cis_return",
        "self_assessment",
        "sa_payment",
        "mtd_itsa_quarterly",
        "mtd_itsa_final",
        "partnership_return",
        "auto_enrolment_redeclaration",
        "periodic",
    }


# ---------------------------------------------------------------- Companies House


@pytest.mark.parametrize(
    ("made_up_to", "due"),
    [("31/03/2026", "31/12/2026")],
)
def test_ch_accounts_uses_the_dates_as_given(made_up_to, due):
    [p] = run(
        "ch_accounts",
        "12/10/2026",
        next_accounts_made_up_to=d(made_up_to),
        next_accounts_due=d(due),
    )
    assert p.period_end == d(made_up_to)
    assert p.due_date == d(due)
    assert p.label == "Year end 31/03/2026"
    assert p.source == "companies_house"


def test_ch_accounts_period_start_follows_the_last_accounts_or_incorporation():
    [p] = run(
        "ch_accounts",
        "12/10/2026",
        last_accounts_made_up_to=d("31/03/2025"),
        next_accounts_made_up_to=d("31/03/2026"),
        next_accounts_due=d("31/12/2026"),
    )
    assert p.period_start == d("01/04/2025")
    [first] = run(
        "ch_accounts",
        "12/10/2026",
        incorporated_on=d("15/06/2025"),
        next_accounts_made_up_to=d("30/06/2026"),
        next_accounts_due=d("15/03/2027"),
    )
    assert first.period_start == d("15/06/2025")


def test_ch_accounts_without_companies_house_data_gives_nothing():
    assert run("ch_accounts", "12/10/2026") == []


@pytest.mark.parametrize(
    ("made_up_to", "next_due", "period_end", "due"),
    [
        ("20/10/2026", "03/11/2026", "20/10/2026", "03/11/2026"),
        ("19/10/2026", None, "19/10/2026", "02/11/2026"),
    ],
)
def test_confirmation_statement(made_up_to, next_due, period_end, due):
    [p] = run(
        "confirmation_statement",
        "12/10/2026",
        next_statement_made_up_to=d(made_up_to),
        next_statement_due=d(next_due) if next_due else None,
    )
    assert p.period_end == d(period_end)
    assert p.due_date == d(due)
    assert p.label == f"Period end {period_end}"


# ---------------------------------------------------------------- corporation tax


@pytest.mark.parametrize(
    ("accounts_end", "return_due"),
    [
        ("31/03/2026", "31/03/2027"),
        ("28/02/2026", "28/02/2027"),
        ("30/06/2026", "30/06/2027"),
        ("29/02/2028", "28/02/2029"),
    ],
)
def test_ct600_is_due_twelve_months_after_the_accounts_period(accounts_end, return_due):
    periods = run(
        "ct600",
        "12/10/2025",
        next_accounts_made_up_to=d(accounts_end),
        last_accounts_made_up_to=None,
        incorporated_on=None,
    )
    assert [p.due_date for p in periods] == [d(return_due)]


def long_period() -> dict:
    return {
        "incorporated_on": d("01/01/2025"),
        "next_accounts_made_up_to": d("31/03/2026"),
        "next_accounts_due": d("31/12/2026"),
    }


def test_a_long_accounts_period_has_two_tax_periods_with_one_return_date():
    periods = run("ct600", "12/10/2025", **long_period())
    assert [(p.period_start, p.period_end) for p in periods] == [
        (d("01/01/2025"), d("31/12/2025")),
        (d("01/01/2026"), d("31/03/2026")),
    ]
    assert {p.due_date for p in periods} == {d("31/03/2027")}


def test_a_long_accounts_period_has_two_payments():
    periods = run("ct_payment", "05/11/2026", **long_period())
    assert sorted(p.due_date for p in periods) == [d("01/10/2026"), d("01/01/2027")]


def test_an_accounts_period_of_twelve_months_is_one_tax_period():
    periods = run(
        "ct600",
        "12/10/2025",
        incorporated_on=d("01/04/2025"),
        next_accounts_made_up_to=d("31/03/2026"),
    )
    assert [(p.period_start, p.period_end) for p in periods] == [(d("01/04/2025"), d("31/03/2026"))]


def test_the_previous_period_is_included_while_its_return_is_not_yet_due():
    kwargs = {
        "last_accounts_made_up_to": d("31/03/2026"),
        "next_accounts_made_up_to": d("31/03/2027"),
    }
    periods = run("ct600", "12/10/2026", **kwargs)
    assert [p.period_end for p in periods] == [d("31/03/2026"), d("31/03/2027")]
    later = run("ct600", "01/04/2027", **kwargs)
    assert [p.period_end for p in later] == [d("31/03/2027")]


def test_ct_payment_is_created_sixty_days_before_it_is_due():
    kwargs = {"next_accounts_made_up_to": d("31/03/2026")}  # payment due 01/01/2027
    assert run("ct_payment", "01/11/2026", **kwargs) == []
    [p] = run("ct_payment", "03/11/2026", **kwargs)
    assert p.due_date == d("01/01/2027")


# ---------------------------------------------------------------- VAT


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
def test_vat_return_due_dates(period_end, due):
    periods = run("vat_return", "28/02/2027", vat_frequency="monthly")
    assert by_key(periods)[d(period_end).isoformat()].due_date == d(due)


def test_quarterly_vat_follows_the_stagger():
    for stagger, months in {1: (3, 6, 9, 12), 2: (1, 4, 7, 10), 3: (2, 5, 8, 11)}.items():
        periods = run("vat_return", "12/10/2026", vat_frequency="quarterly", vat_stagger=stagger)
        assert {d_.month for d_ in (p.period_end for p in periods)} == set(months)
        assert all(p.label.startswith("Quarter ended") for p in periods)


def test_vat_is_created_thirty_days_before_the_period_ends():
    kwargs = {"vat_frequency": "quarterly", "vat_stagger": 1}
    ends = lambda today: [p.period_end for p in run("vat_return", today, **kwargs)]  # noqa: E731
    assert d("31/12/2026") not in ends("30/11/2026")
    assert d("31/12/2026") in ends("01/12/2026")


def test_annual_accounting_vat_is_due_two_months_after_the_year_end():
    periods = run(
        "vat_return",
        "12/10/2026",
        vat_frequency="annual",
        vat_scheme="annual_accounting",
        vat_year_end_month=3,
    )
    assert by_key(periods)["2026-03-31"].due_date == d("31/05/2026")
    assert by_key(periods)["2026-03-31"].label == "Year ended 31/03/2026"


def test_vat_without_settings_gives_nothing():
    assert run("vat_return", "12/10/2026") == []
    assert run("vat_return", "12/10/2026", vat_frequency="quarterly") == []


# ---------------------------------------------------------------- payroll


@pytest.mark.parametrize(
    ("rule_name", "pay_day", "year", "month", "expected"),
    [
        ("day_of_month", 25, 2026, 10, "23/10/2026"),  # the 25th is a Sunday
        ("day_of_month", 25, 2026, 12, "24/12/2026"),  # the 25th is a bank holiday
        ("last_working_day", None, 2026, 8, "28/08/2026"),  # the 31st is a bank holiday
        ("last_working_day", None, 2026, 10, "30/10/2026"),
        ("last_working_day", None, 2026, 12, "31/12/2026"),
        ("day_of_month", 31, 2026, 11, "30/11/2026"),  # November has no 31st
        ("last_friday", None, 2026, 10, "30/10/2026"),
    ],
)
def test_monthly_pay_date(rule_name, pay_day, year, month, expected):
    assert dates.monthly_pay_date(year, month, rule_name, pay_day) == d(expected)


def test_payroll_run_monthly_labels_and_dates():
    periods = run(
        "payroll_run",
        "12/10/2026",
        payroll_frequency="monthly",
        pay_day_rule="day_of_month",
        pay_day=25,
    )
    october = by_key(periods)["2026-10-31"]
    assert (october.label, october.due_date) == ("October 2026", d("23/10/2026"))
    assert max(p.due_date for p in periods) <= d("12/11/2026")  # nothing beyond 31 days ahead


def test_payroll_run_is_created_31_days_ahead():
    kwargs = {"payroll_frequency": "monthly", "pay_day_rule": "day_of_month", "pay_day": 25}
    assert d("25/11/2026") not in [p.due_date for p in run("payroll_run", "24/10/2026", **kwargs)]
    assert d("25/11/2026") in [p.due_date for p in run("payroll_run", "25/10/2026", **kwargs)]


def test_weekly_pay_steps_from_the_first_date_and_moves_back_to_a_working_day():
    periods = run(
        "payroll_run",
        "01/12/2026",
        payroll_frequency="weekly",
        first_pay_date=d("04/12/2026"),
    )
    due = [p.due_date for p in periods if p.due_date >= d("04/12/2026")]
    assert due[:4] == [d("04/12/2026"), d("11/12/2026"), d("18/12/2026"), d("24/12/2026")]
    assert periods[0].label.startswith("Pay date ")


def test_fortnightly_and_four_weekly_steps():
    fortnightly = run(
        "payroll_run", "01/12/2026", payroll_frequency="fortnightly", first_pay_date=d("04/12/2026")
    )
    assert [p.due_date for p in fortnightly if p.due_date >= d("04/12/2026")][:2] == [
        d("04/12/2026"),
        d("18/12/2026"),
    ]
    four = run(
        "payroll_run", "01/12/2026", payroll_frequency="four_weekly", first_pay_date=d("04/12/2026")
    )
    # 01/01/2027 is a bank holiday, so the second pay date moves back to 31/12/2026
    assert [p.due_date for p in four if p.due_date >= d("04/12/2026")] == [
        d("04/12/2026"),
        d("31/12/2026"),
    ]


def test_paye_payment_due_and_pay_by_hint():
    periods = run("paye_payment", "25/09/2026")
    p = by_key(periods)["2026-11-05"]
    assert p.due_date == d("22/11/2026")
    assert "Pay by 20/11/2026" in p.note


def test_paye_quarterly_payers_pay_on_22_jul_oct_jan_apr():
    periods = run("paye_payment", "01/09/2026", settings={"paye_quarterly": True})
    assert {p.due_date for p in periods if p.due_date >= d("01/09/2026")} == {d("22/10/2026")}
    later = run("paye_payment", "01/12/2026", settings={"paye_quarterly": True})
    assert {p.due_date for p in later if p.due_date >= d("01/12/2026")} == {d("22/01/2027")}
    assert {p.due_date.month for p in later} <= {1, 4, 7, 10}


def test_payroll_year_end_is_31_may():
    periods = run("payroll_year_end", "01/04/2027")
    p = by_key(periods)["2027-04-05"]
    assert (p.label, p.due_date) == ("Tax year 2026/27", d("31/05/2027"))


def test_cis_return_due_on_the_19th():
    periods = run("cis_return", "01/11/2026")
    p = by_key(periods)["2026-11-05"]
    assert p.due_date == d("19/11/2026")
    assert p.label == "Month ended 05/11/2026"


# ---------------------------------------------------------------- tax years


def test_self_assessment_2025_26_is_due_31_january_2027():
    periods = run("self_assessment", "12/10/2026")
    p = by_key(periods)["2026-04-05"]
    assert (p.label, p.due_date) == ("Tax year 2025/26", d("31/01/2027"))
    assert "2026-10-05" not in by_key(periods)


def test_self_assessment_is_created_once_the_tax_year_has_ended():
    assert "2026-04-05" not in by_key(run("self_assessment", "05/04/2026"))
    assert "2026-04-05" in by_key(run("self_assessment", "06/04/2026"))


def test_self_assessment_is_skipped_for_a_year_in_making_tax_digital():
    periods = by_key(run("self_assessment", "12/10/2027", mtd_start="2026-04"))
    assert "2027-04-05" not in periods  # 2026/27 is in MTD
    assert "2026-04-05" in periods  # 2025/26 is not


def test_sa_payment_dates():
    periods = run("sa_payment", "01/06/2027", payments_on_account=True)
    due = {p.due_date for p in periods}
    assert d("31/07/2027") in due
    without = {p.due_date for p in run("sa_payment", "01/06/2027", payments_on_account=False)}
    assert d("31/07/2027") not in without


@pytest.mark.xfail(
    strict=True,
    reason="Spec 03 section 6 labels this case tax year 2026/27, but 31/07/2027 is the second "
    "payment on account for 2025/26 (31 July after the tax year ends). See STATUS.md.",
)
def test_sa_second_payment_on_account_for_2026_27_as_the_spec_labels_it():
    periods = run("sa_payment", "01/06/2027", payments_on_account=True)
    second = [p for p in periods if "second payment" in p.label and "2026/27" in p.label]
    assert [p.due_date for p in second] == [d("31/07/2027")]


def test_sa_second_payment_on_account_for_2025_26_is_31_july_2027():
    periods = run("sa_payment", "01/06/2027", payments_on_account=True)
    second = [p for p in periods if "second payment" in p.label and "2025/26" in p.label]
    assert [p.due_date for p in second] == [d("31/07/2027")]


def test_mtd_quarterly_due_dates_for_2026_27():
    periods = run("mtd_itsa_quarterly", "01/07/2026", mtd_start="2026-04")
    got = {p.label: p.due_date for p in periods}
    assert got["Q1 2026/27"] == d("07/08/2026")
    later = {
        p.label: p.due_date for p in run("mtd_itsa_quarterly", "01/04/2027", mtd_start="2026-04")
    }
    assert later["Q2 2026/27"] == d("07/11/2026")
    assert later["Q3 2026/27"] == d("07/02/2027")
    assert later["Q4 2026/27"] == d("07/05/2027")


def test_mtd_quarterly_only_for_tax_years_from_the_start_year():
    periods = run("mtd_itsa_quarterly", "01/04/2027", mtd_start="2027-04")
    assert all("2026/27" not in p.label for p in periods)
    assert run("mtd_itsa_quarterly", "01/04/2027", mtd_start="") == []
    assert run("mtd_itsa_quarterly", "01/04/2027", mtd_start="not_in_scope") == []


def test_mtd_calendar_quarters_change_only_the_label():
    plain = run("mtd_itsa_quarterly", "01/04/2027", mtd_start="2026-04")
    calendar = run(
        "mtd_itsa_quarterly",
        "01/04/2027",
        mtd_start="2026-04",
        settings={"calendar_quarters": True},
    )
    assert [p.due_date for p in plain] == [p.due_date for p in calendar]
    assert all("calendar" in p.label for p in calendar)


def test_mtd_final_declaration_2026_27_is_due_31_january_2028():
    periods = run("mtd_itsa_final", "15/12/2027", mtd_start="2026-04")
    assert by_key(periods)["2027-04-05"].due_date == d("31/01/2028")


def test_p11d_dates():
    periods = run("p11d", "01/06/2026")
    forms = [p for p in periods if p.due_date == d("06/07/2026")]
    class_1a = [p for p in periods if p.due_date == d("22/07/2026")]
    assert forms and "2025/26" in forms[0].label
    assert class_1a and "Class 1A" in class_1a[0].label


def test_partnership_return_is_due_31_january():
    periods = run("partnership_return", "15/12/2026")
    assert by_key(periods)["2026-04-05"].due_date == d("31/01/2027")


# ---------------------------------------------------------------- auto-enrolment


@pytest.mark.parametrize(
    ("anchor", "anniversary", "opens", "closes", "due"),
    [
        ("01/10/2023", "01/10/2026", "01/07/2026", "01/01/2027", "28/02/2027"),
        ("01/07/2023", "01/07/2026", "01/04/2026", "01/10/2026", "30/11/2026"),
        ("01/02/2024", "01/02/2027", "01/11/2026", "01/05/2027", "30/06/2027"),
    ],
)
def test_auto_enrolment_cycle(anchor, anniversary, opens, closes, due):
    from apps.services.rules.auto_enrolment import reenrolment_cycle

    got_anniversary, (got_opens, got_closes), got_due = reenrolment_cycle(d(anchor))
    assert (got_anniversary, got_opens, got_closes, got_due) == (
        d(anniversary),
        d(opens),
        d(closes),
        d(due),
    )


def test_auto_enrolment_is_created_180_days_before_the_due_date():
    kwargs = {"auto_enrolment_start": d("01/10/2023")}  # due 28/02/2027
    assert run("auto_enrolment_redeclaration", "01/08/2026", **kwargs) == []
    [p] = run("auto_enrolment_redeclaration", "02/09/2026", **kwargs)
    assert (p.period_start, p.period_end, p.due_date) == (
        d("01/07/2026"),
        d("01/01/2027"),
        d("28/02/2027"),
    )


def test_auto_enrolment_anchors_on_the_last_re_enrolment_when_set():
    [p] = run(
        "auto_enrolment_redeclaration",
        "01/09/2026",
        auto_enrolment_start=d("01/10/2017"),
        last_reenrolment=d("01/10/2023"),
    )
    assert p.due_date == d("28/02/2027")


# ---------------------------------------------------------------- periodic


def test_periodic_monthly_bookkeeping_due_14_days_after_the_month_end():
    periods = run("periodic", "20/10/2026", settings={"frequency": "monthly", "due_days": 14})
    p = by_key(periods)["2026-09-30"]
    assert (p.label, p.due_date) == ("Period ended 30/09/2026", d("14/10/2026"))


def test_periodic_quarterly_uses_the_end_month():
    periods = run(
        "periodic",
        "20/10/2026",
        settings={"frequency": "quarterly", "end_month": 3, "due_days": 20},
    )
    assert {p.period_end.month for p in periods} <= {3, 6, 9, 12}
    assert d("30/09/2026") in [p.period_end for p in periods]


def test_periodic_renewal_is_due_on_its_date():
    periods = run(
        "periodic",
        "20/10/2026",
        settings={
            "frequency": "annual",
            "end_month": 11,
            "end_day": 15,
            "due_days": 0,
            "renewal": True,
        },
    )
    [p] = [p for p in periods if p.period_end == d("15/11/2026")]
    assert (p.label, p.due_date) == ("Renewal 15/11/2026", d("15/11/2026"))


def test_periodic_without_a_frequency_gives_nothing():
    assert run("periodic", "20/10/2026") == []
