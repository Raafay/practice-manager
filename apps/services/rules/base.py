"""What every deadline rule takes and returns.

A rule is a plain function `rule(inputs) -> list[Period]` with no database access.
`inputs.today` is passed in, so a table of cases can pin the date. A rule returns the
periods it considers due to exist today (it applies its own "created N days ahead"
rule); the job then drops periods that fall before the service started.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

SOURCE_COMPANIES_HOUSE = "companies_house"
SOURCE_CALCULATED = "calculated"

# CORRECTIONS 10: reminder-only rules, and tax-year rules with no stated horizon.
DEFAULT_HORIZON_DAYS = 60


@dataclass(frozen=True)
class Period:
    key: str  # unique for a client and rule
    label: str
    due_date: date
    period_start: date | None = None
    period_end: date | None = None
    source: str = SOURCE_CALCULATED
    note: str = ""


@dataclass(frozen=True)
class Inputs:
    """The dates and settings a rule may use. Everything is optional."""

    today: date
    start: date | None = None  # when the client service starts
    # Companies House dates held on the client
    incorporated_on: date | None = None
    last_accounts_made_up_to: date | None = None
    next_accounts_made_up_to: date | None = None
    next_accounts_due: date | None = None
    last_statement_made_up_to: date | None = None
    next_statement_made_up_to: date | None = None
    next_statement_due: date | None = None
    # VAT
    vat_frequency: str = ""
    vat_stagger: int | None = None
    vat_scheme: str = ""
    vat_year_end_month: int | None = None
    # Payroll
    payroll_frequency: str = ""
    pay_day_rule: str = ""
    pay_day: int | None = None
    first_pay_date: date | None = None
    # Other client details
    payments_on_account: bool | None = None
    mtd_start: str = ""
    auto_enrolment_start: date | None = None
    last_reenrolment: date | None = None
    # Service-specific settings from the client service (frequency, due_days, ...)
    settings: dict = field(default_factory=dict)


Rule = Callable[[Inputs], list[Period]]


@dataclass(frozen=True)
class RuleInfo:
    name: str
    func: Rule
    title: str
    # Rules 1 to 4 always create the current open obligation, whatever the start date.
    always_current: bool = False
    # A reminder date with no task by default.
    reminder_only: bool = False


REGISTRY: dict[str, RuleInfo] = {}


def rule(name: str, title: str, *, always_current: bool = False, reminder_only: bool = False):
    def decorator(func: Rule) -> Rule:
        REGISTRY[name] = RuleInfo(name, func, title, always_current, reminder_only)
        return func

    return decorator


def iso(d: date) -> str:
    return d.isoformat()


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def day_after(d: date) -> date:
    return d + timedelta(days=1)


def within(today: date, due: date, days: int) -> bool:
    """True once today is at least `days` days before `due`."""
    return today >= due - timedelta(days=days)
