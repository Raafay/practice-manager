"""The merge-field renderer. Swaps known `{{ name }}` fields and nothing else.

User-written templates never go through the Django template engine, so a
template cannot run code. An unknown field is reported and blocks sending.
Link fields whose pages are not built yet render a labelled placeholder and
also block sending (CORRECTIONS 24).
"""

import re
from dataclasses import dataclass, field
from datetime import date

import nh3
from django.utils import timezone
from django.utils.html import escape, format_html, format_html_join, linebreaks
from django.utils.safestring import mark_safe

from apps.core.money import format_money

FIELD_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")

# name: (group, description). The order is the order shown in the editor.
FIELDS: dict[str, tuple[str, str]] = {
    "practice.name": ("Practice", "Practice name"),
    "practice.phone": ("Practice", "Practice phone"),
    "practice.email": ("Practice", "Practice email"),
    "practice.address": ("Practice", "Practice address"),
    "user.name": ("Sender", "Sender's full name"),
    "user.first_name": ("Sender", "Sender's first name"),
    "user.job_title": ("Sender", "Sender's job title"),
    "user.signature": ("Sender", "Sender's signature"),
    "client.name": ("Client", "Client name"),
    "client.trading_name": ("Client", "Trading name"),
    "client.ref": ("Client", "Client reference"),
    "client.company_number": ("Client", "Company number"),
    "client.year_end": ("Client", "Year end"),
    "contact.first_name": ("Contact", "Contact's first name"),
    "contact.last_name": ("Contact", "Contact's last name"),
    "contact.full_name": ("Contact", "Contact's full name"),
    "deadline.label": ("Deadline", "What is due"),
    "deadline.due_date": ("Deadline", "Due date"),
    "deadline.period_end": ("Deadline", "Period end"),
    "task.title": ("Task", "Task title"),
    "task.target_date": ("Task", "Task target date"),
    "services_list": ("Blocks", "The client's services as a list"),
    "monthly_fee": ("Money", "Monthly fee total"),
    "setup_fee": ("Money", "One-off fees total"),
    "proposal_link": ("Links", "Button: the proposal"),
    "sign_link": ("Links", "Button: sign the engagement letter"),
    "portal_link": ("Links", "Button: client portal"),
    "upload_link": ("Links", "Button: upload documents"),
    "request_link": ("Links", "Button: make a request"),
    "confirm_link": ("Links", "Button: check company details"),
    "cs01_data": ("Blocks", "What Companies House holds, to confirm"),
    "proposal_summary": ("Blocks", "The proposal's services and charges"),
    "outstanding_invoices": ("Blocks", "Overdue invoices from Xero"),
    "today": ("Date", "Today's date"),
}

LINK_FIELDS = {
    "proposal_link": "Proposal",
    "sign_link": "Sign",
    "portal_link": "Client portal",
    "upload_link": "Upload documents",
    "request_link": "Make a request",
    "confirm_link": "Check your details",
}

# Later stages register a function (client, extra) -> url for a link field.
LINK_BUILDERS: dict = {}


@dataclass
class Context:
    client: object = None
    contact: object = None
    user: object = None
    deadline: object = None
    task: object = None
    extra: dict = field(default_factory=dict)  # link urls by field name, for tests and Stage 7+


@dataclass
class Rendered:
    html: str
    text: str
    unknown: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.unknown or self.placeholders)

    def problems(self) -> list[str]:
        out = [f"Unknown merge field {{{{ {name} }}}}." for name in self.unknown]
        out += [f"{name} is not available yet." for name in self.placeholders]
        return out


def html_to_text(value: str) -> str:
    """A plain-text version of cleaned HTML."""
    value = re.sub(r"(?i)<br\s*/?>", "\n", value or "")
    value = re.sub(r"(?i)</(p|div|li|h1|blockquote|pre)>", "\n", value)
    value = re.sub(r"(?i)<li[^>]*>", "• ", value)
    value = re.sub(r'(?is)<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"\2 (\1)", value)
    value = nh3.clean(value, tags=set())
    value = value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    value = value.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _fmt_date(value) -> str:
    return value.strftime("%d/%m/%Y") if isinstance(value, date) else ""


def _money(value) -> str:
    return format_money(value) if value is not None else ""


def _plain_values(ctx: Context) -> dict[str, str]:
    from apps.core.models import PracticeSettings

    practice = PracticeSettings.load()
    client, contact, user = ctx.client, ctx.contact, ctx.user
    deadline, task = ctx.deadline, ctx.task
    values = {
        "practice.name": practice.practice_name,
        "practice.phone": practice.phone,
        "practice.email": practice.email,
        "practice.address": practice.address,
        "today": _fmt_date(timezone.localdate()),
    }
    if user is not None:
        first = (user.name or "").split(" ")[0]
        values.update(
            {
                "user.name": user.name,
                "user.first_name": first,
                "user.job_title": user.job_title,
                "user.signature": user.email_signature,
            }
        )
    else:
        values.update({"user.name": "", "user.first_name": "", "user.job_title": ""})
        values["user.signature"] = ""
    if client is not None:
        values.update(
            {
                "client.name": client.name,
                "client.trading_name": client.trading_name or client.name,
                "client.ref": client.reference,
                "client.company_number": client.company_number,
                "client.year_end": client.year_end,
            }
        )
    if contact is not None:
        values.update(
            {
                "contact.first_name": contact.preferred_name or contact.first_name,
                "contact.last_name": contact.last_name,
                "contact.full_name": f"{contact.first_name} {contact.last_name}".strip(),
            }
        )
    if deadline is not None:
        values.update(
            {
                "deadline.label": deadline.label,
                "deadline.due_date": _fmt_date(deadline.due_date),
                "deadline.period_end": _fmt_date(deadline.period_end),
            }
        )
    if task is not None:
        values.update({"task.title": task.title, "task.target_date": _fmt_date(task.target_date)})
    if client is not None and client.pk:
        from apps.services.services import summary

        info = summary(client)
        values["monthly_fee"] = _money(info["monthly"])
        values["setup_fee"] = _money(info["one_off"])
    return values


def _services_block(client):
    names = []
    if client is not None and client.pk:
        names = [
            cs.service.name
            for cs in client.client_services.filter(state="active").select_related("service")
        ]
    if not names:
        return "", ""
    items = format_html_join("", "<li>{}</li>", ((n,) for n in names))
    return (
        format_html("<ul>{}</ul>", items),
        "\n".join(f"• {n}" for n in names),
    )


def _outstanding_block(client, today=None):
    """A list of the client's overdue invoices. Empty when there are none."""
    if client is None or not client.pk:
        return "", ""
    from apps.finance.invoicing import overdue_invoices

    today = today or timezone.localdate()
    invoices = list(
        overdue_invoices(today).filter(contact__client=client).order_by("due_date", "id")
    )
    if not invoices:
        return "", ""
    # A list, not a table: the cleaner that runs on every message drops table tags.
    items = format_html_join(
        "",
        "<li>{}: {} due {} ({} days overdue)</li>",
        (
            (i.number, _money(i.amount_due), _fmt_date(i.due_date), i.days_overdue(today))
            for i in invoices
        ),
    )
    html = format_html("<ul>{}</ul>", items)
    text = "\n".join(
        f"• {i.number}: {_money(i.amount_due)} due {_fmt_date(i.due_date)} "
        f"({i.days_overdue(today)} days overdue)"
        for i in invoices
    )
    return html, text


def _cs01_block(client):
    """What Companies House holds, built from the last sync. Shareholders are not in the feed."""
    snapshot = getattr(client, "ch_snapshot", None) if client is not None and client.pk else None
    if snapshot is None:
        return "", ""
    profile = snapshot.profile or {}
    lines: list[tuple[str, str]] = []
    office = profile.get("registered_office_address") or {}
    address = ", ".join(
        str(office[k])
        for k in (
            "premises",
            "address_line_1",
            "address_line_2",
            "locality",
            "region",
            "postal_code",
            "country",
        )
        if office.get(k)
    )
    lines.append(("Registered office", address or "not held"))
    sic = ", ".join(profile.get("sic_codes") or []) or "none held"
    lines.append(("SIC codes", sic))
    for officer in snapshot.officers or []:
        if officer.get("resigned_on"):
            continue
        role = (officer.get("officer_role") or "officer").replace("-", " ")
        since = officer.get("appointed_on")
        lines.append(
            (
                role.capitalize(),
                f"{officer.get('name', '')}, appointed "
                f"{_fmt_date(_parse(since)) or 'date not held'}",
            )
        )
    for owner in snapshot.owners or []:
        if owner.get("ceased_on"):
            continue
        nature = "; ".join(n.replace("-", " ") for n in owner.get("natures_of_control") or [])
        lines.append(
            ("Person with significant control", f"{owner.get('name', '')}: {nature or 'not held'}")
        )
    statement = (profile.get("confirmation_statement") or {}).get("next_made_up_to")
    if statement:
        lines.append(("Statement date", _fmt_date(_parse(statement))))
    ask = (
        "Please also confirm the shareholders and share capital. "
        "Companies House does not list them in the information we receive."
    )
    html = "<ul>{}</ul><p>{}</p>".format(
        "".join(format_html("<li><strong>{}:</strong> {}</li>", k, v) for k, v in lines),
        escape(ask),
    )
    text = "\n".join(f"• {k}: {v}" for k, v in lines) + "\n\n" + ask
    return mark_safe(html), text  # noqa: S308 - every value above was escaped


def _parse(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def render(source: str, ctx: Context, *, html: bool = True) -> Rendered:
    """Fill in a template. `source` is cleaned HTML (or plain text when html is False)."""
    plain = _plain_values(ctx)
    unknown: list[str] = []
    placeholders: list[str] = []
    block_cache: dict[str, tuple] = {}

    def block(name):
        if name not in block_cache:
            if name == "services_list":
                block_cache[name] = _services_block(ctx.client)
            elif name == "cs01_data":
                block_cache[name] = _cs01_block(ctx.client)
            elif name == "proposal_summary":  # built by Stage 9 so it follows the fee switches
                block_cache[name] = ctx.extra.get("proposal_summary_block", ("", ""))
            else:  # outstanding_invoices: read from the Xero data (Stage 11)
                block_cache[name] = _outstanding_block(ctx.client, ctx.extra.get("today"))
        return block_cache[name]

    def link(name):
        url = ctx.extra.get(name)
        builder = LINK_BUILDERS.get(name)
        if not url and builder and ctx.client is not None:
            url = builder(ctx.client, ctx)
        label = LINK_FIELDS[name]
        if not url:
            if name not in placeholders:
                placeholders.append(name)
            return f"[{label} link: not available yet]", f"[{label} link: not available yet]", True
        return label, str(url), False

    def swap(as_html: bool):
        def repl(match):
            name = match.group(1)
            if name not in FIELDS:
                if name not in unknown:
                    unknown.append(name)
                return (
                    f'<mark class="merge-unknown">{{{{ {escape(name)} }}}}</mark>'
                    if as_html
                    else f"{{{{ {name} }}}}"
                )
            if name in ("services_list", "cs01_data", "outstanding_invoices", "proposal_summary"):
                h, t = block(name)
                return str(h) if as_html else t
            if name in LINK_FIELDS:
                label, url, missing = link(name)
                if missing:
                    return (
                        f'<mark class="merge-unknown">{escape(label)}</mark>' if as_html else label
                    )
                if as_html:
                    return format_html(
                        '<a href="{}" style="display:inline-block;padding:8px 14px;'
                        "background:#2f5d8a;color:#fff;border-radius:4px;"
                        'text-decoration:none">{}</a>',
                        url,
                        label,
                    )
                return f"{label}: {url}"
            value = plain.get(name, "")
            if name == "user.signature" and as_html:
                return str(linebreaks(escape(value))) if value else ""
            return escape(value) if as_html else value

        return repl

    body_html = FIELD_PATTERN.sub(swap(True), source) if html else ""
    if html:
        text = html_to_text(FIELD_PATTERN.sub(swap(False), _text_source(source)))
    else:
        text = FIELD_PATTERN.sub(swap(False), source)
        body_html = str(linebreaks(escape(text)))
    return Rendered(html=body_html, text=text, unknown=unknown, placeholders=placeholders)


def _text_source(source: str) -> str:
    return source


def render_subject(subject: str, ctx: Context) -> Rendered:
    """Subjects are plain text, so fields are swapped without HTML escaping."""
    result = render(subject, ctx, html=False)
    return result


def find_fields(source: str) -> list[str]:
    return FIELD_PATTERN.findall(source or "")


def unknown_fields(*sources: str) -> list[str]:
    seen: list[str] = []
    for source in sources:
        for name in find_fields(source):
            if name not in FIELDS and name not in seen:
                seen.append(name)
    return seen
