"""Columns of the client list: label, how to sort, and how to write them to CSV."""

from django.db.models import F

from .models import Client

# key: (label, ordering expressions ascending, csv getter)
COLUMNS = {
    "name": ("Name", ["name"], lambda c: c.name),
    "reference": ("Reference", ["reference"], lambda c: c.reference),
    "type": ("Type", ["client_type", "name"], lambda c: c.get_client_type_display()),
    "status": ("Status", ["status", "name"], lambda c: c.get_status_display()),
    "manager": (
        "Manager",
        ["manager__name", "name"],
        lambda c: c.manager.name if c.manager else "",
    ),
    "partner": (
        "Partner",
        ["partner__name", "name"],
        lambda c: c.partner.name if c.partner else "",
    ),
    "team": (
        "Team",
        ["team__name", "name"],
        lambda c: c.team.name if c.team else "",
    ),
    "year_end": (
        "Year end",
        ["accounting_ref_month", "accounting_ref_day"],
        lambda c: c.year_end,
    ),
    "company_number": (
        "Company number",
        ["company_number"],
        lambda c: c.company_number,
    ),
    "email": ("Email", ["email"], lambda c: c.email),
    "phone": ("Phone", ["phone"], lambda c: c.phone),
    "client_since": (
        "Client since",
        ["client_since"],
        lambda c: c.client_since.strftime("%d/%m/%Y") if c.client_since else "",
    ),
    "tags": ("Tags", [], lambda c: ", ".join(t.name for t in c.tags.all())),
}
# Stage 4 adds next deadline and monthly fee (the fee only with fees.view).

DEFAULT_COLUMNS = ["name", "type", "manager", "partner", "year_end", "tags"]


def clean_columns(keys) -> list[str]:
    chosen = [k for k in keys if k in COLUMNS]
    if "name" not in chosen:
        chosen.insert(0, "name")
    return list(dict.fromkeys(chosen))


def ordering_for(sort: str) -> list:
    """Order by a column key, '-key' for descending. Unknown keys fall back to name."""
    descending = sort.startswith("-")
    names = COLUMNS.get(sort.lstrip("-"), COLUMNS["name"])[1] or COLUMNS["name"][1]
    if descending:
        return [F(n).desc(nulls_last=True) for n in names] + [F("name").asc()]
    return [F(n).asc(nulls_last=True) for n in names] + [F("name").asc()]


def valid_sort(sort: str) -> str:
    key = sort.lstrip("-")
    return sort if key in COLUMNS and COLUMNS[key][1] else ""


def csv_row(client: Client, keys) -> list[str]:
    return [COLUMNS[k][2](client) for k in keys]
