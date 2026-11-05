"""The practice's look in one place: name, logo, colours, email footer, PDF letterhead.

Pages read the colours as CSS variables on <html> (--color-accent, --color-brand), emails
add the footer, and PDFs use the same letterhead. When the app serves several practices,
this is the one function that changes to pick the right practice.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

WHITE_TEXT_CONTRAST = 4.5  # WCAG AA for normal text


def _luminance(hex_colour: str) -> float:
    channels = []
    for i in (1, 3, 5):
        c = int(hex_colour[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(hex_colour: str) -> float:
    return 1.05 / (_luminance(hex_colour) + 0.05)


def validate_readable_with_white(value: str) -> None:
    """White text must stay readable on this colour (buttons, the top bar)."""
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value or "") and (
        contrast_with_white(value) < WHITE_TEXT_CONTRAST
    ):
        raise ValidationError(
            "This colour is too light for white text on it. Choose a darker shade."
        )


def theme(practice=None) -> dict:
    if practice is None:
        from .models import PracticeSettings

        practice = PracticeSettings.load()
    return {
        "name": practice.practice_name,
        "accent": practice.accent_colour or "#2f5d8a",
        "brand": practice.brand_colour or "#0f172a",
        "email_footer": practice.email_footer.strip(),
        "address": practice.address,
        "has_logo": bool(practice.logo),
    }


def css_variables(practice) -> str:
    t = theme(practice)
    return f"--color-accent: {t['accent']}; --color-brand: {t['brand']}"
