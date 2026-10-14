"""The fields an import file can fill, how a heading is matched to one, and how values are cleaned.

Every cleaner returns the cleaned value or raises Problem with a message for the owner.
Fixed lists accept common spellings; anything not recognised is a problem, never a guess.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.companieshouse.api import InvalidNumber, normalise_number

from .models import Kind


class Problem(ValueError):
    """A value that cannot be used. The message is shown to the owner."""


def norm(text: str) -> str:
    """Lower case, punctuation to spaces, single spaces. Used for headings and fixed lists."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


# ---------------------------------------------------------------- cleaners


def clean_text(value: str, max_length: int = 200) -> str:
    text = " ".join(value.split()) if "\n" not in value else value.strip()
    if len(text) > max_length:
        raise Problem(f"longer than {max_length} characters")
    return text


DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


def clean_date(value: str) -> date:
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise Problem(f"“{text}” is not a date. Use dd/mm/yyyy or yyyy-mm-dd")


def clean_money(value: str) -> Decimal:
    text = value.strip().replace("£", "").replace(",", "").replace(" ", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise Problem(f"“{value.strip()}” is not an amount of money") from None
    if amount < 0:
        raise Problem("cannot be negative")
    if amount >= Decimal("100000000"):
        raise Problem("too large")
    return amount.quantize(Decimal("0.01"))


YES = {"yes", "y", "true", "1", "on"}
NO = {"no", "n", "false", "0", "off"}


def clean_yes_no(value: str) -> bool:
    text = norm(value)
    if text in YES:
        return True
    if text in NO:
        return False
    raise Problem(f"“{value.strip()}” is not yes or no")


def clean_email(value: str) -> str:
    text = value.strip().lower()
    try:
        validate_email(text)
    except ValidationError:
        raise Problem(f"“{value.strip()}” is not an email address") from None
    return text


def clean_company_number(value: str) -> str:
    try:
        return normalise_number(value)
    except InvalidNumber:
        raise Problem(f"“{value.strip()}” is not a company number") from None


def clean_utr(value: str) -> str:
    digits = re.sub(r"\s+", "", value)
    if not re.fullmatch(r"\d{10}", digits):
        # The value itself is never repeated: it may be a real tax reference.
        raise Problem("not ten digits")
    return digits


MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def clean_year_end(value: str) -> tuple[int, int]:
    """(day, month) from 31/03, 31/03/2026, 2026-03-31, 31 March or March (last day)."""
    text = value.strip()
    try:
        found = clean_date(text)
        return found.day, found.month
    except Problem:
        pass
    words = norm(text).split()
    day = month = None
    if re.fullmatch(r"\d{1,2}/\d{1,2}", text):
        day, month = (int(p) for p in text.split("/"))
    elif len(words) == 2 and words[0].isdigit() and words[1] in MONTHS:
        day, month = int(words[0]), MONTHS[words[1]]
    elif len(words) == 1 and words[0] in MONTHS:
        month = MONTHS[words[0]]
        day = 28 if month == 2 else DAYS_IN_MONTH[month - 1]
    if month is None or not 1 <= month <= 12 or not 1 <= day <= DAYS_IN_MONTH[month - 1]:
        raise Problem(f"“{text}” is not a year end. Use dd/mm, for example 31/03")
    return day, month


def choice_cleaner(spellings: dict[str, tuple[str, ...]], what: str):
    """A cleaner for a fixed list. spellings: stored value -> accepted spellings."""
    lookup = {}
    for stored, names in spellings.items():
        lookup[norm(stored)] = stored
        for name in names:
            lookup[norm(name)] = stored

    def clean(value: str) -> str:
        found = lookup.get(norm(value))
        if found is None:
            raise Problem(f"“{value.strip()}” is not a {what} we know")
        return found

    clean.lookup = lookup
    return clean


CLIENT_TYPES = choice_cleaner(
    {
        "ltd": (
            "limited company",
            "private limited company",
            "private limited",
            "limited",
            "ltd company",
            "company",
            "private company",
            "limited by shares",
        ),
        "plc": ("public limited company", "public company"),
        "llp": ("limited liability partnership",),
        "partnership": ("general partnership", "partnerships"),
        "sole_trader": ("sole trader", "self employed", "sole proprietor", "soletrader"),
        "individual": ("person", "personal", "personal tax", "private individual"),
        "trust": ("trusts",),
        "charity": ("charitable company", "cio", "charitable incorporated organisation"),
        "other": (),
    },
    "client type",
)
STATUSES = choice_cleaner(
    {
        "prospect": ("lead",),
        "onboarding": ("new client", "setting up"),
        "active": ("live", "current", "engaged"),
        "paused": ("on hold", "suspended"),
        "former": ("ceased", "left", "ex client", "former client", "disengaged"),
        "lost": (),
    },
    "status",
)
VAT_FREQUENCIES = choice_cleaner(
    {
        "monthly": ("month", "1 monthly", "m"),
        "quarterly": ("quarter", "3 monthly", "q", "qtr"),
        "annual": ("annually", "yearly", "year", "a"),
    },
    "VAT frequency",
)
SOURCES = choice_cleaner(
    {
        "word_of_mouth": ("word of mouth", "recommendation"),
        "client_referral": ("client referral", "referred by a client", "referred by client"),
        "accountant_referral": (
            "accountant referral",
            "referred by an accountant",
            "referred by accountant",
        ),
        "website": ("web", "online", "internet", "web site"),
        "other": (),
    },
    "source",
)
ROLES = choice_cleaner(
    {
        "director": ("directors", "managing director", "md"),
        "secretary": ("company secretary",),
        "shareholder": ("shareholders", "owner"),
        "psc": ("person with significant control", "person of significant control"),
        "partner": (),
        "member": ("designated member", "llp member"),
        "trustee": (),
        "employee": ("staff", "staff member"),
        "bookkeeper": ("book keeper",),
        "other": (),
    },
    "role",
)
FEE_FREQUENCIES = choice_cleaner(
    {
        "monthly": ("month", "per month", "pm", "p m", "m"),
        "quarterly": ("quarter", "per quarter", "q", "qtr"),
        "annual": ("annually", "yearly", "year", "per year", "per annum", "pa", "p a", "y"),
        "one_off": ("one off", "oneoff", "once", "single"),
    },
    "fee frequency",
)
STAGGER_MONTHS = {3: 1, 6: 1, 9: 1, 12: 1, 1: 2, 4: 2, 7: 2, 10: 2, 2: 3, 5: 3, 8: 3, 11: 3}


def clean_stagger(value: str) -> int:
    words = norm(value).replace("stagger", "").split()
    if len(words) == 1 and words[0] in ("1", "2", "3"):
        return int(words[0])
    if words and words[0] in MONTHS:
        return STAGGER_MONTHS[MONTHS[words[0]]]
    raise Problem(f"“{value.strip()}” is not a VAT stagger. Use 1, 2 or 3, or the first month")


def clean_roles(value: str) -> list[str]:
    parts = [p for p in re.split(r"[,;/|]", value) if p.strip()]
    return list(dict.fromkeys(ROLES(p) for p in parts))


def clean_tags(value: str) -> list[str]:
    names = [" ".join(p.split()) for p in re.split(r"[,;|]", value)]
    names = [n for n in names if n]
    if any(len(n) > 50 for n in names):
        raise Problem("a tag is longer than 50 characters")
    return list(dict.fromkeys(names))


# ---------------------------------------------------------------- fields


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    cleaner: object = clean_text
    synonyms: tuple[str, ...] = ()
    # Never shown back or written to the failures file.
    sensitive: bool = False
    help: str = ""
    extra: dict = field(default_factory=dict)

    def clean(self, value: str):
        return self.cleaner(value)


def _text(n: int):
    return lambda v: clean_text(v, n)


CLIENT_FIELDS = [
    FieldDef("name", "Name", _text(200), ("client name", "company name", "business name")),
    FieldDef("client_type", "Type", CLIENT_TYPES, ("client type", "entity type", "business type")),
    FieldDef("status", "Status", STATUSES, ("client status",)),
    FieldDef(
        "reference",
        "Client reference",
        _text(20),
        ("reference", "ref", "client ref", "client code", "code", "client no", "client number"),
    ),
    FieldDef(
        "company_number",
        "Company number",
        clean_company_number,
        ("company no", "company reg", "crn", "registration number", "company registration number"),
    ),
    FieldDef(
        "manager", "Manager (name or email)", _text(200), ("client manager", "account manager")
    ),
    FieldDef("partner", "Partner (name or email)", _text(200), ("client partner",)),
    FieldDef("email", "Email", clean_email, ("email address", "e mail", "client email")),
    FieldDef("phone", "Phone", _text(40), ("telephone", "phone number", "tel", "landline")),
    FieldDef("address_1", "Address line 1", _text(200), ("address", "address 1", "street")),
    FieldDef("address_2", "Address line 2", _text(200), ("address 2",)),
    FieldDef("address_3", "Address line 3", _text(200), ("address 3", "town", "city")),
    FieldDef("address_4", "Address line 4", _text(200), ("address 4", "county")),
    FieldDef("postcode", "Postcode", _text(12), ("post code", "postal code", "zip")),
    FieldDef("vat_number", "VAT number", _text(20), ("vat no", "vat reg", "vrn", "vat reg no")),
    FieldDef(
        "vat_frequency", "VAT frequency", VAT_FREQUENCIES, ("vat period", "vat return frequency")
    ),
    FieldDef("vat_stagger", "VAT stagger", clean_stagger, ("vat quarter", "vat quarters")),
    FieldDef(
        "paye_reference", "PAYE reference", _text(30), ("paye ref", "employer reference", "paye")
    ),
    FieldDef(
        "accounts_office_reference",
        "Accounts Office reference",
        _text(30),
        ("accounts office ref", "ao ref", "aoref"),
    ),
    FieldDef(
        "year_end",
        "Year end",
        clean_year_end,
        ("accounting year end", "financial year end", "accounting reference date", "ye"),
    ),
    FieldDef(
        "utr",
        "UTR",
        clean_utr,
        ("unique taxpayer reference", "tax reference", "ct utr", "corporation tax utr"),
        sensitive=True,
    ),
    FieldDef("client_since", "Client since", clean_date, ("date joined", "client start date")),
    FieldDef("source", "Source", SOURCES, ("lead source", "referral source")),
    FieldDef("tags", "Tags", clean_tags, ("labels", "groups")),
    FieldDef("notes", "Notes", _text(5000), ("note", "comments", "memo")),
]

CLIENT_LINK_HELP = "The client's reference, company number or exact name."

CONTACT_FIELDS = [
    FieldDef("client", "Client", _text(200), ("client name", "company", "client ref")),
    FieldDef("title", "Title", _text(20), ("salutation",)),
    FieldDef("first_name", "First name", _text(100), ("forename", "given name", "first")),
    FieldDef("last_name", "Last name", _text(100), ("surname", "family name", "last")),
    FieldDef("full_name", "Full name", _text(200), ("name", "contact name", "contact")),
    FieldDef("email", "Email", clean_email, ("email address", "e mail")),
    FieldDef("mobile", "Mobile", _text(40), ("mobile phone", "mobile number", "cell")),
    FieldDef("phone", "Phone", _text(40), ("telephone", "phone number", "tel")),
    FieldDef("date_of_birth", "Date of birth", clean_date, ("dob", "birth date", "born")),
    FieldDef("role", "Role", clean_roles, ("roles", "position", "relationship")),
    FieldDef("is_main", "Main contact", clean_yes_no, ("is main contact", "primary contact")),
    FieldDef(
        "receives_reminders",
        "Receives reminders",
        clean_yes_no,
        ("reminders", "send reminders"),
    ),
]

SERVICE_FIELDS = [
    FieldDef("client", "Client", _text(200), ("client name", "company", "client ref")),
    FieldDef("service", "Service (name or code)", _text(100), ("service name", "job", "work")),
    FieldDef("fee", "Fee", clean_money, ("amount", "price", "fee amount", "charge")),
    FieldDef("frequency", "Frequency", FEE_FREQUENCIES, ("fee frequency", "billing frequency")),
    FieldDef("start_date", "Start date", clean_date, ("starts", "starts on", "from")),
]

FIELDS: dict[str, list[FieldDef]] = {
    Kind.CLIENTS: CLIENT_FIELDS,
    Kind.CONTACTS: CONTACT_FIELDS,
    Kind.SERVICES: SERVICE_FIELDS,
}


def fields_for(kind: str) -> dict[str, FieldDef]:
    return {f.key: f for f in FIELDS[kind]}


def suggest(kind: str, headers: list[str]) -> dict[str, str]:
    """{heading: field key or ""}. Exact names first, then a heading that contains a name.

    Each field is suggested for one heading only.
    """
    defs = FIELDS[kind]
    names = {f.key: {norm(f.label), norm(f.key)} | {norm(s) for s in f.synonyms} for f in defs}
    taken: set[str] = set()
    result = dict.fromkeys(headers, "")
    for heading in headers:
        n = norm(heading)
        for f in defs:
            if f.key not in taken and n in names[f.key]:
                result[heading] = f.key
                taken.add(f.key)
                break
    for heading in headers:
        if result[heading]:
            continue
        n = f" {norm(heading)} "
        for f in defs:
            if f.key in taken:
                continue
            if any(len(s) > 3 and f" {s} " in n for s in names[f.key]):
                result[heading] = f.key
                taken.add(f.key)
                break
    return result


def header_key(headers: list[str]) -> str:
    return "|".join(norm(h) for h in headers)[:500]
