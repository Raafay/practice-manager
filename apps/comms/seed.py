"""The eight starter reminder schedules and their templates (fresh wording, all switched off).

Kept in one place so the migration and tests read the same list. Wording is a
placeholder for the practice to replace before go-live (DECISIONS part 2, point 18).
"""

HELLO = "<p>Dear {{ contact.first_name }},</p>"
BYE = "<p>Kind regards,<br>{{ user.name }}</p>"

TEMPLATES = [
    {
        "key": "accounts_records",
        "name": "Accounts: records request",
        "group": "records",
        "subject": "Records needed for {{ client.name }}'s year-end accounts",
        "body": HELLO + "<p>{{ client.name }}'s financial year ended on {{ deadline.period_end }}. "
        "To prepare the "
        "accounts we need your bank statements, sales and purchase records, and any loan or "
        "asset paperwork for the year.</p><p>The accounts are due at Companies House by "
        "{{ deadline.due_date }}. Please reply to this email with everything attached.</p>" + BYE,
    },
    {
        "key": "confirmation_statement",
        "name": "Confirmation statement: details to check",
        "group": "deadline",
        "subject": "Please check the details we hold for {{ client.name }}",
        "body": HELLO
        + "<p>{{ client.name }}'s confirmation statement is due on {{ deadline.due_date }}. "
        "Here is what Companies House holds today. Please read it and tell us if anything has "
        "changed.</p>{{ cs01_data }}<p>If it is all correct, just reply to say so.</p>" + BYE,
    },
    {
        "key": "vat_records",
        "name": "VAT: records request",
        "group": "records",
        "subject": "VAT records for the period to {{ deadline.period_end }}",
        "body": HELLO
        + "<p>The VAT period for {{ client.name }} ended on {{ deadline.period_end }}. Please send "
        "your sales invoices, purchase invoices and bank statements for the period. The return "
        "is due by {{ deadline.due_date }}. Reply to this email with them attached.</p>" + BYE,
    },
    {
        "key": "sa_records",
        "name": "Self assessment: records request",
        "group": "records",
        "subject": "Your tax return: information we need",
        "body": HELLO
        + "<p>The tax year has ended, so it is time to gather what is needed for your self "
        "assessment return. Please send your income details, bank interest, dividends, pension "
        "contributions and anything else that changed this year. The return is due by "
        "{{ deadline.due_date }}. Reply to this email with them attached.</p>" + BYE,
    },
    {
        "key": "payroll_changes",
        "name": "Payroll: changes request",
        "group": "records",
        "subject": "Payroll changes for {{ deadline.due_date }}",
        "body": HELLO
        + "<p>The next payroll for {{ client.name }} runs on {{ deadline.due_date }}. "
        "Please tell us "
        "about new starters, leavers, pay rises, overtime and any absence before then.</p>" + BYE,
    },
    {
        "key": "ct_payment",
        "name": "Corporation tax: payment reminder",
        "group": "reminder",
        "subject": "Corporation tax payment due {{ deadline.due_date }}",
        "body": HELLO
        + "<p>This is a reminder that {{ client.name }}'s corporation tax is due to be paid by "
        "{{ deadline.due_date }}. Payment goes to HMRC directly.</p>" + BYE,
    },
    {
        "key": "sa_payment",
        "name": "Self assessment: payment reminder",
        "group": "reminder",
        "subject": "Tax payment due {{ deadline.due_date }}",
        "body": HELLO
        + "<p>A payment towards your tax bill is due by {{ deadline.due_date }}. Payment goes to "
        "HMRC directly. Tell us if you would like help working out the amount.</p>" + BYE,
    },
    {
        "key": "paye_payment",
        "name": "PAYE: payment reminder",
        "group": "reminder",
        "subject": "PAYE payment due {{ deadline.due_date }}",
        "body": HELLO + "<p>{{ client.name }}'s PAYE and National Insurance is due to HMRC by "
        "{{ deadline.due_date }}.</p>" + BYE,
    },
]

SCHEDULES = [
    {
        "key": "accounts_records",
        "name": "Accounts records request",
        "rule": "ch_accounts",
        "trigger": "after_period_end",
        "offsets": [7],
        "repeat_every_days": 21,
        "max_repeats": 4,
        "description": "7 days after the year end, then every 21 days, up to 4 more times. "
        "Stops when “Records received” is ticked.",
    },
    {
        "key": "confirmation_statement",
        "name": "Confirmation statement details",
        "rule": "confirmation_statement",
        "trigger": "before_deadline",
        "offsets": [28],
        "repeat_every_days": 7,
        "max_repeats": 3,
        "description": "28 days before the statement date, then every 7 days, up to 3 more "
        "times. Stops when “Client confirmed” is ticked.",
    },
    {
        "key": "vat_records",
        "name": "VAT records request",
        "rule": "vat_return",
        "trigger": "after_period_end",
        "offsets": [5],
        "repeat_every_days": 5,
        "max_repeats": 3,
        "description": "5 days after the period ends, then every 5 days, up to 3 more times. "
        "Stops when “Records received” is ticked.",
    },
    {
        "key": "sa_records",
        "name": "Self assessment records request",
        "rule": "self_assessment",
        "trigger": "after_period_end",
        "offsets": [15],
        "repeat_every_days": 30,
        "max_repeats": 6,
        "description": "20 April (15 days after the tax year ends), then every 30 days, up to "
        "6 more times. Stops when “Records received” is ticked.",
    },
    {
        "key": "payroll_changes",
        "name": "Payroll changes request",
        "rule": "payroll_run",
        "trigger": "before_deadline",
        "offsets": [5],
        "working_days": True,
        "description": "5 working days before pay day. Stops when “Changes received” is ticked.",
    },
    {
        "key": "ct_payment",
        "name": "Corporation tax payment reminder",
        "rule": "ct_payment",
        "trigger": "before_deadline",
        "offsets": [30, 7],
        "description": "30 days and 7 days before the payment date.",
    },
    {
        "key": "sa_payment",
        "name": "Self assessment payment reminder",
        "rule": "sa_payment",
        "trigger": "before_deadline",
        "offsets": [14],
        "description": "14 days before 31 January and 31 July.",
    },
    {
        "key": "paye_payment",
        "name": "PAYE payment reminder",
        "rule": "paye_payment",
        "trigger": "before_deadline",
        "offsets": [5],
        "description": "The 17th of each month (5 days before the PAYE due date).",
    },
]
