"""Deadline rules. Importing this package registers all seventeen."""

from . import (  # noqa: F401 - each module registers its rules
    auto_enrolment,
    companies_house,
    payroll,
    periodic,
    tax_year,
    vat,
)
from .base import REGISTRY, Inputs, Period, RuleInfo

__all__ = ["REGISTRY", "Inputs", "Period", "RuleInfo"]
