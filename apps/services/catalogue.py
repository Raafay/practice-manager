"""The service catalogue seeded by the first migration (docs/specs/03 section 1)."""

COMPANIES = ["ltd", "plc"]
COMPANIES_LLPS = ["ltd", "plc", "llp"]
INDIVIDUALS = ["individual", "sole_trader"]
ALL = [
    "ltd",
    "plc",
    "llp",
    "partnership",
    "sole_trader",
    "individual",
    "trust",
    "charity",
    "other",
]

# code, name, kind, applies_to, rules, renewal
SEED = [
    ("accounts", "Accounts", "compliance", COMPANIES_LLPS, ["ch_accounts"], False),
    ("ct600", "CT600 Return", "compliance", COMPANIES, ["ct600", "ct_payment"], False),
    (
        "confirmation",
        "Confirmation Statement",
        "compliance",
        COMPANIES_LLPS,
        ["confirmation_statement"],
        False,
    ),
    ("bookkeeping", "Bookkeeping", "compliance", ALL, ["periodic"], False),
    ("vat", "VAT Returns", "compliance", ALL, ["vat_return"], False),
    (
        "payroll",
        "Payroll",
        "compliance",
        ALL,
        ["payroll_run", "paye_payment", "payroll_year_end"],
        False,
    ),
    (
        "auto_enrolment",
        "Auto-Enrolment",
        "compliance",
        ALL,
        ["auto_enrolment_redeclaration"],
        False,
    ),
    ("management_accounts", "Management Accounts", "compliance", ALL, ["periodic"], False),
    ("cis", "CIS", "compliance", ALL, ["cis_return"], False),
    ("p11d", "P11D", "compliance", ALL, ["p11d"], False),
    ("fee_protection", "Fee Protection Service", "compliance", ALL, ["periodic"], True),
    (
        "self_assessment",
        "Self Assessment",
        "compliance",
        INDIVIDUALS,
        ["self_assessment", "sa_payment"],
        False,
    ),
    (
        "mtd_income_tax",
        "MTD for Income Tax",
        "compliance",
        INDIVIDUALS,
        ["mtd_itsa_quarterly", "mtd_itsa_final"],
        False,
    ),
    (
        "partnership_return",
        "Partnership Return",
        "compliance",
        ["partnership"],
        ["partnership_return"],
        False,
    ),
    ("registered_office", "Registered Office", "compliance", COMPANIES_LLPS, ["periodic"], True),
    ("fractional_fd", "Fractional Finance Director", "advisory", ALL, [], False),
    ("training", "Training and Coaching", "advisory", ALL, [], False),
    ("operations_support", "Operations and Controls Support", "advisory", ALL, [], False),
]

# Default days after the period end, by service code (rule 17).
DEFAULT_DUE_DAYS = {"bookkeeping": 14, "management_accounts": 20, "fee_protection": 0}
