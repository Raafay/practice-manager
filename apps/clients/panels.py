"""The panels on the Info tab: which fields each holds and when it applies."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import models

from apps.core.fields import EncryptedTextField, mask

from .models import Client, CustomFieldDefinition

# Dates the Companies House sync fills in Stage 3. Read-only once a company number is set.
SYNCED_DATE_FIELDS = (
    "last_accounts_made_up_to",
    "next_accounts_made_up_to",
    "next_accounts_due",
    "last_statement_made_up_to",
    "next_statement_made_up_to",
    "next_statement_due",
)

# Everything the Companies House sync writes. Read-only once a company number is set
# (CORRECTIONS 11). Trading name, nature of business and the authentication code stay
# editable: Companies House does not supply them.
COMPANIES_HOUSE_FIELDS = (
    "company_status",
    "incorporated_on",
    "registered_office",
    "sic_codes",
    "accounting_ref_day",
    "accounting_ref_month",
    *SYNCED_DATE_FIELDS,
)

COMPANY_FIELDS = [
    "company_number",
    "company_status",
    "incorporated_on",
    "registered_office",
    "sic_codes",
    "trading_name",
    "nature_of_business",
    "accounting_ref_day",
    "accounting_ref_month",
    *SYNCED_DATE_FIELDS,
    "ch_auth_code",
]

TAX_COMMON = [
    "vat_number",
    "vat_registered_on",
    "vat_frequency",
    "vat_stagger",
    "vat_scheme",
    "vat_year_end_month",
    "paye_reference",
    "accounts_office_reference",
    "payroll_frequency",
    "pay_day_rule",
    "pay_day",
    "first_pay_date",
    "employee_count",
    "cis_role",
    "pension_provider",
    "auto_enrolment_start",
    "last_reenrolment",
]

INTERNAL_FIELDS = [
    "source",
    "referred_by_client",
    "referred_by_text",
    "client_since",
    "tags",
    "payment_method",
    "no_auto_messages",
]

# Shown but never edited here: set by status changes, Companies House or later stages.
INTERNAL_READ_ONLY = [
    "relationship_ended_on",
    "retain_until",
    "aml_retain_until",
    "xero_contact_id",
]


@dataclass(frozen=True)
class Panel:
    key: str
    title: str
    editable: bool = True


PANELS = {
    "required": Panel("required", "Required information"),
    "main_contact": Panel("main_contact", "Main contact", editable=False),
    "company": Panel("company", "Company details"),
    "tax": Panel("tax", "Tax and registration"),
    "contact": Panel("contact", "Contact details"),
    "internal": Panel("internal", "Internal"),
}


_WORDS = {"vat": "VAT", "utr": "UTR", "paye": "PAYE", "sic": "SIC", "cis": "CIS", "aml": "AML"}


def pretty_label(label) -> str:
    """Sentence case that keeps acronyms and Companies House in capitals."""
    text = str(label)
    text = text[:1].upper() + text[1:]
    text = re.sub(
        r"\b(vat|utr|paye|sic|cis|aml)\b", lambda m: _WORDS[m.group(1).lower()], text, flags=re.I
    )
    return re.sub(r"companies house", "Companies House", text, flags=re.I)


def visible_panels(client: Client) -> list[Panel]:
    """Panels that apply to this client's type. A sole trader has no Company details."""
    return [p for p in PANELS.values() if p.key != "company" or client.is_company]


def panel_fields(key: str, client: Client) -> list[str]:
    if key == "required":
        return ["name", "client_type", "reference", "partner", "manager", "team"]
    if key == "company":
        return list(COMPANY_FIELDS)
    if key == "tax":
        fields = list(TAX_COMMON)
        if not client.is_individual:
            fields.insert(0, "company_utr")
        if client.is_individual:
            fields += ["mtd_start", "payments_on_account"]
        return fields
    if key == "contact":
        return ["email", "phone", "website", "correspondence_address"]
    if key == "internal":
        return list(INTERNAL_FIELDS)
    return []


def format_custom(definition: CustomFieldDefinition, raw: str) -> str:
    if raw in ("", None):
        return ""
    if definition.kind == CustomFieldDefinition.Kind.YES_NO:
        return "Yes" if raw == "yes" else "No"
    if definition.kind == CustomFieldDefinition.Kind.DATE:
        try:
            year, month, day = raw.split("-")
            return f"{day}/{month}/{year}"
        except ValueError:
            return str(raw)
    return str(raw)


def rows_for(client: Client, key: str, user) -> list[dict]:
    """Label and value pairs for the read-only view of a panel.

    kind tells the template how to show the value: text, date, datetime, bool, tags,
    link, multiline or masked (with reveal_url). Empty values are kept so the panel
    shows what could be filled in.
    """
    if key == "main_contact":
        return []
    names = panel_fields(key, client)
    if key == "required":
        names.insert(2, "status")
    if key == "company":
        names.append("last_synced_at")
    if key == "internal":
        names += INTERNAL_READ_ONLY
    rows = []
    for name in names:
        field = client._meta.get_field(name)
        label = pretty_label(field.verbose_name)
        row = {"label": label, "name": name, "kind": "text", "value": getattr(client, name, None)}
        if isinstance(field, EncryptedTextField):
            value = getattr(client, name)
            row.update(kind="masked", value=mask(value) if value else "", reveal=bool(value))
        elif field.many_to_many:
            row.update(kind="tags", value=list(client.tags.all()))
        elif isinstance(field, models.BooleanField):
            row.update(kind="bool", value=getattr(client, name))
        elif isinstance(field, models.DateTimeField):
            row["kind"] = "datetime"
        elif isinstance(field, models.DateField):
            row["kind"] = "date"
        elif field.is_relation:
            value = getattr(client, name)
            row["value"] = value
            if isinstance(value, Client):
                row.update(kind="client")
        elif field.choices:
            row["value"] = getattr(client, f"get_{name}_display")() if row["value"] else ""
        elif isinstance(field, models.TextField):
            row["kind"] = "multiline"
        if name == "company_number" and client.company_number:
            row.update(
                kind="link", url=client.companies_house_url, link_text="View on Companies House"
            )
        if name == "status":
            row["kind"] = "status"
        if name == "pay_day_rule" and client.pay_day_rule:
            row["value"] = client.get_pay_day_rule_display()
        rows.append(row)
    if key == "company" and client.company_number:
        for row in rows:
            if row["name"] in COMPANIES_HOUSE_FIELDS:
                row["note"] = "From Companies House"
    if key == "internal":
        for definition in CustomFieldDefinition.objects.all():
            raw = client.custom_values.get(str(definition.pk), "")
            rows.append(
                {
                    "label": definition.name,
                    "kind": "text",
                    "value": format_custom(definition, raw),
                    "name": f"cf_{definition.pk}",
                }
            )
    return rows
