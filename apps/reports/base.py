"""The pattern every report follows: a filter form, figures, a table, and the same rows as CSV.

A report is a class with a key, a form and `build(data, user)`. The page and the export
are generic views in this app, so each report is only its query.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django import forms

from apps.core.forms import DateInput, StyledFormMixin


@dataclass(frozen=True)
class Column:
    label: str
    numeric: bool = False


@dataclass(frozen=True)
class Link:
    """A cell that links to a page. CSV gets the text only."""

    text: str
    url: str

    def __str__(self) -> str:
        return self.text


@dataclass
class Section:
    """A small summary table shown above the main one."""

    title: str
    columns: list[Column]
    rows: list[list]


@dataclass
class Result:
    columns: list[Column]
    rows: list[list]
    figures: list[tuple[str, object]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


class Report:
    key = ""
    title = ""
    description = ""
    icon = "chart-bar"
    form_class: type[forms.Form]
    empty = "Nothing matches these filters. Widen them and try again."

    def form(self, params, user):
        return self.form_class(params or None, user=user)

    def build(self, data: dict, user) -> Result:
        raise NotImplementedError


class ReportForm(StyledFormMixin, forms.Form):
    """Filter forms take the user, so a filter can depend on what the person may see."""

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    @property
    def data_or_empty(self) -> dict:
        return self.cleaned_data if self.is_valid() else {}


def date_field(label: str) -> forms.DateField:
    return forms.DateField(required=False, label=label, widget=DateInput())


def hours(minutes) -> Decimal:
    return (Decimal(minutes or 0) / 60).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def one_place(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def in_range(queryset, name: str, start: date | None, end: date | None):
    if start:
        queryset = queryset.filter(**{f"{name}__gte": start})
    if end:
        queryset = queryset.filter(**{f"{name}__lte": end})
    return queryset
