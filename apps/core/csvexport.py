"""CSV downloads. Every export in the app goes through here, so no cell can run as a formula.

A spreadsheet treats a cell that starts with = + - @ (or a tab or carriage return
before one) as a formula. Text cells that start that way get a quote mark in front.
Numbers and dates are written as they are: they cannot carry a formula.
"""

import csv
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    """The value as CSV text, with a leading quote mark if a spreadsheet would run it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value)
    return "'" + text if text[:1] in FORMULA_STARTS else text


class SafeWriter:
    """csv.writer that makes every cell safe."""

    def __init__(self, handle):
        self._writer = csv.writer(handle)

    def writerow(self, row) -> None:
        self._writer.writerow([safe_cell(v) for v in row])

    def writerows(self, rows) -> None:
        for row in rows:
            self.writerow(row)


def csv_response(filename: str) -> tuple[HttpResponse, SafeWriter]:
    """A download response and a safe writer for it. Never cached."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response, SafeWriter(response)
