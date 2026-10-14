"""Starter checklist and letter wording. The wording is a placeholder (spec 06 section 2)."""

CHECKLIST = [
    ("proposal_accepted", "Proposal accepted", False, True),
    ("engagement_letter_signed", "Engagement letter signed", True, True),
    ("client_details", "Client details form completed", True, False),
    ("identity_verified", "Identity verified for everyone who needs it", True, True),
    ("risk_assessment_approved", "Risk assessment approved", True, True),
    ("professional_clearance", "Clearance from the previous accountant", False, False),
    ("hmrc_authorisations", "HMRC agent authorisations in place", False, True),
    ("companies_house_code", "Companies House authentication code held", False, False),
    ("software_access", "Access to the client's accounting software", False, False),
    ("payment_set_up", "Payment method set up", False, False),
    ("services_confirmed", "Services, fees and start dates confirmed", True, False),
    ("welcome_sent", "Welcome message sent", False, False),
]

LETTER_PARTS = {
    "covering": (
        1,
        "<p>Dear {{ contact.first_name }},</p>"
        "<p>Thank you for choosing {{ practice.name }} to act for {{ client.name }}. "
        "This letter sets out the services we will provide, our fees and the terms on which "
        "we act. Please read it, and if you agree, sign it on screen using the link we sent.</p>"
        "<p>Kind regards,<br>{{ user.name }}</p>",
    ),
    "terms": (
        2,
        "<h2>Standard terms</h2>"
        "<p>We will carry out the services listed in the schedules with reasonable skill and "
        "care. You agree to give us complete and accurate information on time. Fees are payable "
        "as set out in the schedules. Either of us may end this engagement by writing to the "
        "other. We keep records as the law requires.</p>",
    ),
    "privacy": (
        3,
        "<h2>Privacy notice</h2>"
        "<p>We hold the personal information you give us to provide our services, to meet our "
        "legal duties (including anti-money-laundering checks) and to keep in touch. We keep it "
        "secure and only share it where the law or the work needs it. You can ask to see or "
        "correct what we hold about you.</p>",
    ),
}

CHECKLIST_NOTE = "Starter text. Replace with the practice's own wording before use."

TEMPLATES = [
    {
        "key": "engagement_letter_send",
        "name": "Engagement letter: please sign",
        "group": "onboarding",
        "subject": "Your engagement letter from {{ practice.name }}",
        "body": "<p>Dear {{ contact.first_name }},</p>"
        "<p>Your engagement letter for {{ client.name }} is ready. Please read it and sign "
        "it on screen:</p><p>{{ sign_link }}</p>"
        "<p>The link works for 14 days. A PDF copy of the letter is on the page.</p>"
        "<p>Kind regards,<br>{{ user.name }}</p>",
        "send_mode": "hold",
    },
    {
        "key": "engagement_letter_signed",
        "name": "Engagement letter: signed copy",
        "group": "onboarding",
        "subject": "Your signed engagement letter",
        "body": "<p>Dear {{ contact.first_name }},</p>"
        "<p>Thank you for signing. A copy of the signed letter for {{ client.name }} is "
        "attached for your records.</p><p>Kind regards,<br>{{ practice.name }}</p>",
        "send_mode": "hold",
    },
    {
        "key": "clearance_request",
        "name": "Professional clearance request",
        "group": "onboarding",
        "subject": "Professional clearance: {{ client.name }}",
        "channel": "email",
        "body": "<p>Dear colleague,</p>"
        "<p>{{ client.name }} has asked us to act as its accountants. With the client's "
        "consent, and in line with professional clearance practice, please let us know "
        "whether there is any professional reason why we should not accept the appointment, "
        "and send the records listed in the attached letter.</p>"
        "<p>Kind regards,<br>{{ user.name }}<br>{{ practice.name }}</p>",
        "send_mode": "hold",
    },
    {
        "key": "clearance_letter",
        "name": "Professional clearance letter (PDF copy)",
        "group": "onboarding",
        "subject": "Professional clearance: {{ client.name }}",
        "channel": "letter",
        "body": "<p>Dear colleague,</p>"
        "<p>{{ client.name }} has asked us to act as its accountants. With the client's "
        "consent, please let us know whether there is any professional reason why we should "
        "not accept the appointment, and send us the records we have ticked in our email.</p>"
        "<p>Yours faithfully,<br>{{ user.name }}<br>{{ practice.name }}</p>",
        "send_mode": "hold",
    },
    {
        "key": "clearance_chase",
        "name": "Professional clearance: chase",
        "group": "onboarding",
        "subject": "Reminder: professional clearance for {{ client.name }}",
        "channel": "email",
        "body": "<p>Dear colleague,</p>"
        "<p>We wrote about {{ client.name }} a little while ago and have not yet had a reply. "
        "Please could you let us have your clearance and the records we asked for.</p>"
        "<p>Kind regards,<br>{{ user.name }}<br>{{ practice.name }}</p>",
        "send_mode": "hold",
    },
]
