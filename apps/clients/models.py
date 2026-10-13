import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import IntegerField, Max, Q
from django.db.models.functions import Cast, Substr
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import PublicIdModel, TimeStampedModel, validate_hex_colour

COMPANY_TYPES = ("ltd", "plc", "llp")
INDIVIDUAL_TYPES = ("individual", "sole_trader")
# Statuses that show in the client list by default.
DEFAULT_LIST_STATUSES = ("active", "onboarding", "paused")


class Tag(TimeStampedModel):
    name = models.CharField(max_length=50, unique=True)
    colour = models.CharField(max_length=7, default="#64748b", validators=[validate_hex_colour])

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CustomFieldDefinition(TimeStampedModel):
    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        NUMBER = "number", "Number"
        DATE = "date", "Date"
        YES_NO = "yes_no", "Yes or no"

    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self) -> str:
        return self.name


class ClientQuerySet(models.QuerySet):
    def not_archived(self):
        return self.filter(archived_at__isnull=True)

    def archived(self):
        return self.filter(archived_at__isnull=False)


class Client(PublicIdModel, TimeStampedModel):
    class Type(models.TextChoices):
        LTD = "ltd", "Private limited company"
        PLC = "plc", "Public limited company"
        LLP = "llp", "Limited liability partnership"
        PARTNERSHIP = "partnership", "Partnership"
        SOLE_TRADER = "sole_trader", "Sole trader"
        INDIVIDUAL = "individual", "Individual"
        TRUST = "trust", "Trust"
        CHARITY = "charity", "Charity"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        ONBOARDING = "onboarding", "Onboarding"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        FORMER = "former", "Former"
        LOST = "lost", "Lost"

    class VatFrequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"

    class VatScheme(models.TextChoices):
        STANDARD = "standard", "Standard"
        FLAT_RATE = "flat_rate", "Flat rate"
        CASH = "cash", "Cash accounting"
        ANNUAL = "annual_accounting", "Annual accounting"

    class PayrollFrequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        FORTNIGHTLY = "fortnightly", "Fortnightly"
        FOUR_WEEKLY = "four_weekly", "Four-weekly"
        MONTHLY = "monthly", "Monthly"

    class PayDayRule(models.TextChoices):
        DAY_OF_MONTH = "day_of_month", "A day of the month"
        LAST_WORKING_DAY = "last_working_day", "Last working day"
        LAST_FRIDAY = "last_friday", "Last Friday"
        WEEKDAY = "weekday", "A weekday (weekly pay)"

    class CisRole(models.TextChoices):
        NONE = "none", "None"
        CONTRACTOR = "contractor", "Contractor"
        SUBCONTRACTOR = "subcontractor", "Subcontractor"
        BOTH = "both", "Both"

    class MtdStart(models.TextChoices):
        NOT_IN_SCOPE = "not_in_scope", "Not in scope"
        APR_2026 = "2026-04", "April 2026"
        APR_2027 = "2027-04", "April 2027"
        APR_2028 = "2028-04", "April 2028"

    class Source(models.TextChoices):
        WORD_OF_MOUTH = "word_of_mouth", "Word of mouth"
        CLIENT_REFERRAL = "client_referral", "Client referral"
        ACCOUNTANT_REFERRAL = "accountant_referral", "Accountant referral"
        WEBSITE = "website", "Website"
        OTHER = "other", "Other"

    class PaymentMethod(models.TextChoices):
        STANDING_ORDER = "standing_order", "Standing order"
        DIRECT_DEBIT = "direct_debit", "Direct Debit"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    # Required information
    name = models.CharField(max_length=200)
    client_type = models.CharField(max_length=20, choices=Type.choices, default=Type.LTD)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    reference = models.CharField(max_length=20, unique=True, blank=True)
    partner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_clients",
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_clients",
    )
    team = models.ForeignKey(
        "accounts.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="clients"
    )

    # Company details
    company_number = models.CharField(max_length=12, blank=True, db_index=True)
    company_status = models.CharField(max_length=60, blank=True)
    incorporated_on = models.DateField(null=True, blank=True)
    registered_office = models.TextField(blank=True)
    sic_codes = models.CharField("SIC codes", max_length=200, blank=True)
    trading_name = models.CharField(max_length=200, blank=True)
    nature_of_business = models.CharField(max_length=300, blank=True)
    accounting_ref_day = models.PositiveSmallIntegerField(
        "accounting reference day",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    accounting_ref_month = models.PositiveSmallIntegerField(
        "accounting reference month",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    last_accounts_made_up_to = models.DateField(null=True, blank=True)
    next_accounts_made_up_to = models.DateField(null=True, blank=True)
    next_accounts_due = models.DateField(null=True, blank=True)
    last_statement_made_up_to = models.DateField(null=True, blank=True)
    next_statement_made_up_to = models.DateField(null=True, blank=True)
    next_statement_due = models.DateField(null=True, blank=True)
    ch_auth_code = EncryptedTextField("Companies House authentication code", blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    # Tax and registration
    company_utr = EncryptedTextField("company UTR", blank=True)
    vat_number = models.CharField(max_length=20, blank=True)
    vat_registered_on = models.DateField(null=True, blank=True)
    vat_frequency = models.CharField(max_length=10, choices=VatFrequency.choices, blank=True)
    vat_stagger = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=[
            (1, "1: Mar, Jun, Sep, Dec"),
            (2, "2: Jan, Apr, Jul, Oct"),
            (3, "3: Feb, May, Aug, Nov"),
        ],
    )
    vat_scheme = models.CharField(max_length=20, choices=VatScheme.choices, blank=True)
    vat_year_end_month = models.PositiveSmallIntegerField(
        "VAT year end month",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    paye_reference = models.CharField("PAYE reference", max_length=30, blank=True)
    accounts_office_reference = models.CharField(max_length=30, blank=True)
    payroll_frequency = models.CharField(
        max_length=12, choices=PayrollFrequency.choices, blank=True
    )
    pay_day_rule = models.CharField(max_length=20, choices=PayDayRule.choices, blank=True)
    pay_day = models.PositiveSmallIntegerField(
        "pay day (day of month, or weekday 1 = Monday to 7 = Sunday)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    first_pay_date = models.DateField(null=True, blank=True)
    employee_count = models.PositiveIntegerField("number of employees", null=True, blank=True)
    cis_role = models.CharField(max_length=15, choices=CisRole.choices, default=CisRole.NONE)
    pension_provider = models.CharField(max_length=100, blank=True)
    auto_enrolment_start = models.DateField("auto-enrolment duties start", null=True, blank=True)
    last_reenrolment = models.DateField("last re-enrolment date", null=True, blank=True)
    mtd_start = models.CharField(
        "Making Tax Digital for Income Tax start",
        max_length=12,
        choices=MtdStart.choices,
        blank=True,
    )
    payments_on_account = models.BooleanField(null=True, blank=True)

    # Contact details
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    correspondence_address = models.TextField(blank=True)

    # Internal
    source = models.CharField(max_length=20, choices=Source.choices, blank=True)
    referred_by_client = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="referrals"
    )
    referred_by_text = models.CharField("referred by (free text)", max_length=200, blank=True)
    client_since = models.DateField(null=True, blank=True)
    relationship_ended_on = models.DateField(null=True, blank=True)
    retain_until = models.DateField(null=True, blank=True)
    aml_retain_until = models.DateField("AML records retained until", null=True, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="clients")
    custom_values = models.JSONField(default=dict, blank=True)
    payment_method = models.CharField(max_length=15, choices=PaymentMethod.choices, blank=True)
    no_auto_messages = models.BooleanField("do not send automatic messages", default=False)
    xero_contact_id = models.CharField(max_length=60, blank=True)
    request_token = models.CharField(max_length=80, blank=True)

    # Archive
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    archive_reason = models.CharField(max_length=300, blank=True)

    objects = ClientQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["archived_at"])]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = next_reference()
        super().save(*args, **kwargs)

    @property
    def status_tone(self) -> str:
        return {
            "active": "green",
            "onboarding": "accent",
            "prospect": "accent",
            "paused": "amber",
            "lost": "red",
        }.get(self.status, "neutral")

    @property
    def is_company(self) -> bool:
        return self.client_type in COMPANY_TYPES

    @property
    def is_individual(self) -> bool:
        return self.client_type in INDIVIDUAL_TYPES

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def companies_house_url(self) -> str:
        if not self.company_number:
            return ""
        return f"https://find-and-update.company-information.service.gov.uk/company/{self.company_number}"

    @property
    def year_end(self) -> str:
        if self.accounting_ref_day and self.accounting_ref_month:
            return f"{self.accounting_ref_day:02d}/{self.accounting_ref_month:02d}"
        return ""

    @property
    def main_contact(self):
        link = self.client_contacts.filter(is_main=True).select_related("contact").first()
        return link.contact if link else None


def next_reference() -> str:
    """C0001, C0002 and so on: one more than the highest automatic reference in use."""
    highest = Client.objects.filter(reference__regex=r"^C[0-9]+$").aggregate(
        top=Max(Cast(Substr("reference", 2), IntegerField()))
    )["top"]
    return f"C{(highest or 0) + 1:04d}"


class Contact(PublicIdModel, TimeStampedModel):
    title = models.CharField(max_length=20, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    preferred_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    # Companies House gives only the month and year of birth. Used to match officers.
    birth_month = models.PositiveSmallIntegerField(
        "month of birth",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    birth_year = models.PositiveSmallIntegerField("year of birth", null=True, blank=True)
    ni_number = EncryptedTextField("National Insurance number", blank=True)
    personal_utr = EncryptedTextField("personal UTR", blank=True)
    home_address = models.TextField(blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    country_of_residence = models.CharField(max_length=60, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    ch_officer_id = models.CharField("Companies House officer id", max_length=60, blank=True)
    ch_personal_code = EncryptedTextField("Companies House personal code", blank=True)
    ch_identity_verified = models.BooleanField(
        "identity verified with Companies House", default=False
    )
    ch_identity_verified_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["last_name", "first_name"])]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)

    @property
    def display_name(self) -> str:
        return " ".join(p for p in (self.title, self.first_name, self.last_name) if p)


class ClientContact(TimeStampedModel):
    class Role(models.TextChoices):
        DIRECTOR = "director", "Director"
        SECRETARY = "secretary", "Secretary"
        SHAREHOLDER = "shareholder", "Shareholder"
        PSC = "psc", "Person with significant control"
        PARTNER = "partner", "Partner"
        MEMBER = "member", "Member"
        TRUSTEE = "trustee", "Trustee"
        EMPLOYEE = "employee", "Employee"
        BOOKKEEPER = "bookkeeper", "Bookkeeper"
        OTHER = "other", "Other"

    class Source(models.TextChoices):
        MANUAL = "manual", "Added by hand"
        COMPANIES_HOUSE = "companies_house", "Companies House"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_contacts")
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="client_links")
    roles = models.JSONField(default=list, blank=True)
    is_main = models.BooleanField("main contact", default=False)
    receives_reminders = models.BooleanField(default=True)
    can_sign = models.BooleanField(default=False)
    portal_access = models.BooleanField(default=False)
    appointed_on = models.DateField(null=True, blank=True)
    resigned_on = models.DateField(null=True, blank=True)
    shareholding_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)

    class Meta:
        ordering = ["-is_main", "contact__last_name", "contact__first_name"]
        constraints = [
            models.UniqueConstraint(fields=["client", "contact"], name="one_link_per_person"),
            models.UniqueConstraint(
                fields=["client"], condition=Q(is_main=True), name="one_main_contact_per_client"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contact} at {self.client}"

    @property
    def role_labels(self) -> list[str]:
        labels = dict(self.Role.choices)
        return [labels.get(code, code) for code in self.roles]


class ClientLink(TimeStampedModel):
    class Relationship(models.TextChoices):
        PERSONAL_TAX = "personal_tax", "Director's personal tax"
        GROUP = "group", "Group company"
        SAME_OWNER = "same_owner", "Same owner"
        SPOUSE = "spouse", "Spouse or partner"
        OTHER = "other", "Other"

    client_a = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="links_from")
    client_b = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="links_to")
    relationship = models.CharField(
        max_length=15, choices=Relationship.choices, default=Relationship.OTHER
    )
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(client_a=models.F("client_b")), name="no_link_to_self"
            ),
            models.UniqueConstraint(fields=["client_a", "client_b"], name="one_link_per_pair"),
        ]

    def __str__(self) -> str:
        return f"{self.client_a} – {self.client_b}"

    def other(self, client: Client) -> Client:
        return self.client_b if self.client_a_id == client.pk else self.client_a


class Note(TimeStampedModel):
    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        CALL = "call", "Call"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="notes")
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.NOTE)
    text = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pinned = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.text[:60]


def document_upload_to(instance, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"documents/{uuid.uuid4().hex}/{uuid.uuid4().hex}.{extension}"


class DocumentQuerySet(models.QuerySet):
    def live(self):
        return self.filter(deleted_at__isnull=True)


class Document(PublicIdModel, TimeStampedModel):
    class Category(models.TextChoices):
        IDENTITY = "identity", "Identity"
        PROOF_OF_ADDRESS = "proof_of_address", "Proof of address"
        ENGAGEMENT = "engagement", "Engagement"
        ACCOUNTS = "accounts", "Accounts"
        TAX = "tax", "Tax"
        VAT = "vat", "VAT"
        PAYROLL = "payroll", "Payroll"
        BOOKKEEPING = "bookkeeping", "Bookkeeping"
        CORRESPONDENCE = "correspondence", "Correspondence"
        ADVISORY = "advisory", "Advisory"
        OTHER = "other", "Other"

    class Source(models.TextChoices):
        STAFF = "staff", "Staff"
        PORTAL = "portal", "Portal"
        REQUEST = "request", "Request"
        SYSTEM = "system", "System"

    SENSITIVE_BY_DEFAULT = (Category.IDENTITY, Category.PROOF_OF_ADDRESS)

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="documents")
    contact = models.ForeignKey(
        Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=document_upload_to, max_length=200)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    sensitive = models.BooleanField(default=False)
    shared_with_portal = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.STAFF)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["category", "-created_at"]

    def __str__(self) -> str:
        return self.title

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def can_preview(self) -> bool:
        return self.content_type in PREVIEW_TYPES

    def soft_delete(self, user) -> None:
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save(update_fields=["deleted_at", "deleted_by", "updated_at"])


PREVIEW_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/webp")


class SavedView(TimeStampedModel):
    """A name plus the current filters, columns and sort of a list. Private or shared."""

    list_key = models.CharField(max_length=30, default="clients")
    name = models.CharField(max_length=80)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views"
    )
    shared = models.BooleanField("share with everyone", default=False)
    is_default = models.BooleanField("open this view first", default=False)
    filters = models.JSONField(default=dict, blank=True)
    columns = models.JSONField(default=list, blank=True)
    sort = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "list_key"],
                condition=models.Q(is_default=True),
                name="one_default_view_per_list",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if not self.name.strip():
            raise ValidationError("Give the view a name.")
