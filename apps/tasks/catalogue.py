"""Statuses, categories and task templates seeded by migration 0002 (docs/specs/04-tasks.md)."""

# name, colour, is_done, is_waiting, is_default
STATUSES = [
    ("To do", "#64748b", False, False, True),
    ("In progress", "#2563eb", False, False, False),
    ("Waiting on client", "#d97706", False, True, False),
    ("In review", "#7c3aed", False, False, False),
    ("Done", "#16a34a", True, False, False),
]

# name, kind, colour
CATEGORIES = [
    ("Accounts", "compliance", "#2563eb"),
    ("Corporation tax", "compliance", "#7c3aed"),
    ("VAT", "compliance", "#0891b2"),
    ("Payroll", "compliance", "#16a34a"),
    ("Self assessment", "compliance", "#d97706"),
    ("Company secretarial", "compliance", "#db2777"),
    ("Bookkeeping", "compliance", "#0d9488"),
    ("AML", "compliance", "#dc2626"),
    ("Operations", "advisory", "#4f46e5"),
    ("Internal controls", "advisory", "#9333ea"),
    ("Training and coaching", "advisory", "#ea580c"),
    ("Insurance", "advisory", "#0284c7"),
    ("Finance systems", "advisory", "#059669"),
    ("Reporting and budgets", "advisory", "#c026d3"),
    ("Cash flow and funding", "advisory", "#ca8a04"),
    ("HR and payroll queries", "advisory", "#e11d48"),
    ("Supplier and contract queries", "advisory", "#65a30d"),
    ("Other", "advisory", "#64748b"),
    ("Practice admin", "internal", "#475569"),
    ("Sales", "sales", "#0f766e"),
    ("Onboarding", "onboarding", "#1d4ed8"),
]

S, F = "S", "F"  # stops reminders, filing step

# Target rule kinds: days_before_due, working_days_before_due, days_before_ct_payment, fixed_day.
# service code, rule, name pattern, category, (target kind, days or (month, day)), steps
TEMPLATES = [
    (
        "accounts", "ch_accounts", "Accounts Preparation Year End {period_end}", "Accounts",
        ("days_before_due", 60),
        [("Records requested", ""), ("Records received", S), ("Accounts drafted", ""),
         ("Sent to client for approval", ""), ("Approved by client", "")],
    ),
    (
        "accounts", "ch_accounts", "Companies House Submission Year End {period_end}", "Accounts",
        ("days_before_due", 30),
        [("Filed at Companies House", F)],
    ),
    (
        "ct600", "ct600", "CT600 Submission Year End {period_end}", "Corporation tax",
        ("days_before_ct_payment", 14),
        [("Computation prepared", ""), ("Sent for approval", ""), ("Approved", ""),
         ("Filed with HMRC", F), ("Client told the amount and payment date", "")],
    ),
    (
        "confirmation", "confirmation_statement",
        "Confirmation Statement Period End {period_end}", "Company secretarial",
        ("days_before_due", 7),
        [("Details sent to client", ""), ("Client confirmed", S), ("Filed at Companies House", F)],
    ),
    (
        "vat", "vat_return", "VAT Return Period End {period_end}", "VAT",
        ("days_before_due", 7),
        [("Records requested", ""), ("Records received", S), ("Return prepared", ""),
         ("Approved by client", ""), ("Filed", F)],
    ),
    (
        "payroll", "payroll_run", "PAYE {period_label}", "Payroll",
        ("working_days_before_due", 2),
        [("Changes received", S), ("Payroll run", ""), ("Payslips sent", ""),
         ("Submission filed", F)],
    ),
    (
        "payroll", "payroll_year_end", "Payroll Year End {period_label}", "Payroll",
        ("days_before_due", 14),
        [("Final submission filed", ""), ("P60s issued", F)],
    ),
    (
        "bookkeeping", "periodic", "Accounts Bookkeeping Period End {period_end}", "Bookkeeping",
        ("days_before_due", 0),
        [("Records received", S), ("Posted", ""), ("Bank reconciled", F)],
    ),
    (
        "management_accounts", "periodic", "Management Accounts Period End {period_end}",
        "Bookkeeping",
        ("days_before_due", 0),
        [("Prepared", ""), ("Reviewed", ""), ("Sent to client", F)],
    ),
    (
        "cis", "cis_return", "CIS Return Month End {period_end}", "Payroll",
        ("days_before_due", 3),
        [("Details received", S), ("Return filed", F), ("Statements sent", "")],
    ),
    (
        "p11d", "p11d", "P11D {period_label}", "Payroll",
        ("days_before_due", 14),
        [("Benefits details received", S), ("Forms prepared", ""), ("Filed", F)],
    ),
    (
        "self_assessment", "self_assessment", "Self Assessment {period_label}", "Self assessment",
        ("fixed_day", (10, 31)),
        [("Records requested", ""), ("Records received", S), ("Return prepared", ""),
         ("Sent for approval", ""), ("Approved", ""), ("Filed", F),
         ("Client told the amount and payment dates", "")],
    ),
    (
        "mtd_income_tax", "mtd_itsa_quarterly", "MTD Quarterly Update {period_label}",
        "Self assessment",
        ("days_before_due", 7),
        [("Records received", S), ("Update submitted", F)],
    ),
    (
        "mtd_income_tax", "mtd_itsa_final", "MTD Final Declaration {period_label}",
        "Self assessment",
        ("fixed_day", (10, 31)),
        [("Return prepared", ""), ("Approved", ""), ("Filed", F)],
    ),
    (
        "partnership_return", "partnership_return", "Partnership Return {period_label}",
        "Self assessment",
        ("fixed_day", (10, 31)),
        [("Records received", S), ("Return prepared", ""), ("Approved", ""), ("Filed", F)],
    ),
    (
        "auto_enrolment", "auto_enrolment_redeclaration",
        "Auto-Enrolment Re-declaration due {due_date}", "Payroll",
        ("days_before_due", 30),
        [("Staff assessed", ""), ("Re-declaration submitted", F)],
    ),
]
