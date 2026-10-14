"""The starter risk questions, exactly as in spec 06 section 4.

(section, text, risky answer, score, enhanced, records the check, help text)
Scores are for the answer that raises risk; the other answer scores 0.
"""

QUESTIONS = [
    (
        "The client",
        "Have we met the client face to face, or verified them another reliable way?",
        "no",
        2,
        False,
        False,
        "",
    ),
    (
        "The client",
        "Is the client acting on behalf of someone else who has not been identified?",
        "yes",
        5,
        True,
        False,
        "",
    ),
    (
        "The client",
        "Has the client been unusually secretive, evasive or in a hurry?",
        "yes",
        3,
        False,
        False,
        "",
    ),
    (
        "The client",
        "Was the client turned away by, or did they leave, a previous accountant in unclear "
        "circumstances?",
        "yes",
        2,
        False,
        False,
        "",
    ),
    (
        "Ownership",
        "Is the ownership structure complex or hard to follow?",
        "yes",
        3,
        False,
        False,
        "",
    ),
    ("Ownership", "Have all owners with more than 25% been identified?", "no", 5, True, False, ""),
    ("Ownership", "Does any owner or director live outside the UK?", "yes", 2, False, False, ""),
    (
        "Geography",
        "Does the client have owners, customers, suppliers or funds linked to a high-risk country "
        "on the UK government's list?",
        "yes",
        5,
        True,
        False,
        "",
    ),
    ("The business", "Does the business handle a lot of cash?", "yes", 3, False, False, ""),
    (
        "The business",
        "Is the business in a higher-risk sector, for example money transfer, crypto assets, "
        "gambling, scrap metal, used cars, property, or precious metals and stones?",
        "yes",
        3,
        False,
        False,
        "",
    ),
    (
        "The business",
        "Do the turnover and activity we see fit what the client told us?",
        "no",
        4,
        False,
        False,
        "",
    ),
    (
        "People",
        "Is the client, an owner or a close relative or associate a politically exposed person?",
        "yes",
        5,
        True,
        True,
        "Record the date you checked and how.",
    ),
    (
        "People",
        "Did a check against the UK sanctions list find a match?",
        "yes",
        10,
        True,
        True,
        "Stop and speak to the owner before doing anything else. Record the date you checked "
        "and how.",
    ),
    (
        "People",
        "Is there negative news about the client or its owners that bears on honesty?",
        "yes",
        3,
        False,
        False,
        "",
    ),
    ("Our service", "Will we hold or move client money?", "yes", 3, False, False, ""),
    (
        "Our service",
        "Are we forming companies or providing a registered office or director services?",
        "yes",
        2,
        False,
        False,
        "",
    ),
    (
        "Our service",
        "Does the work involve tax planning that is aggressive or unusual?",
        "yes",
        3,
        False,
        False,
        "",
    ),
]


def options_for(risky: str, score: int, enhanced: bool) -> list[dict]:
    out = []
    for value in ("yes", "no"):
        out.append(
            {
                "value": value,
                "label": value.capitalize(),
                "score": score if value == risky else 0,
                "enhanced": bool(enhanced and value == risky),
            }
        )
    return out
