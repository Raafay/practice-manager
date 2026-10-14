"""Starter data: sales stages, proposal wording and the proposal email (all starter text)."""

# (key, name, chance, is_open, is_won, is_lost, is_on_hold, colour)
STAGES = [
    ("enquiry", "Enquiry", 10, True, False, False, False, "#64748b"),
    ("meeting_booked", "Meeting booked", 20, True, False, False, False, "#0ea5e9"),
    ("meeting_held", "Meeting held", 35, True, False, False, False, "#6366f1"),
    ("follow_up", "Follow-up", 45, True, False, False, False, "#a855f7"),
    ("proposal_sent", "Proposal sent", 60, True, False, False, False, "#f59e0b"),
    ("won", "Won", 100, False, True, False, False, "#16a34a"),
    ("lost", "Lost", 0, False, False, True, False, "#dc2626"),
    ("on_hold", "On hold", 5, True, False, False, True, "#94a3b8"),
]

OPENING_TEXT = "Thank you for meeting us. Below is what we would do for you and what it would cost."

WHAT_NEXT_HTML = (
    "<p><strong>Starter text: the practice should replace this.</strong></p>"
    "<ol>"
    "<li>Press <em>Accept</em> on this page, type your full name and confirm.</li>"
    "<li>We will send you an engagement letter to sign on screen.</li>"
    "<li>We will ask you for a few details and for proof of identity, as the law requires "
    "us to check who we act for.</li>"
    "<li>We then contact your previous accountant, if you have one, and agree a start date.</li>"
    "</ol>"
)

TEMPLATE = {
    "key": "proposal_send",
    "name": "Proposal email (starter text, replace with your own)",
    "group": "proposal",
    "subject": "{{ client.name }}: our proposal",
    "body": "<p>Dear {{ contact.first_name }},</p>"
    "<p>Thank you for talking to us about {{ client.name }}. We would be pleased to act "
    "for you. Our proposal is below, and you can read it in full and accept it online.</p>"
    "{{ proposal_summary }}"
    "<p>If you would like anything else included, just reply to this email.</p>"
    "<p>{{ proposal_link }}</p>"
    "<p>Kind regards,<br>{{ user.name }}</p>",
    "send_mode": "hold",
}
