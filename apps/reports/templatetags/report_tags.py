from datetime import date, datetime
from decimal import Decimal

from django import template
from django.utils.html import format_html

from apps.reports.base import Link

register = template.Library()


@register.filter
def cell(value):
    """A report cell for the page: dates as dd/mm/yyyy, money and hours to two places."""
    if value is None or value == "":
        return "—"
    if isinstance(value, Link):
        return format_html('<a href="{}">{}</a>', value.url, value.text)
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, Decimal):
        return f"{value:,}"
    return value
