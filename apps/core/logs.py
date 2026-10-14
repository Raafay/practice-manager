"""Logging helpers. Logs carry no personal data and no secrets (spec 01 section 11).

Addresses that hold a token (invitations, signing links, proposals, request links,
password reset keys) are redacted before a line is written, wherever it comes from:
Django's own warnings, a server error, or the gunicorn access log.
"""

import json
import logging
import re

REDACTED = "[redacted]"
_PATTERNS = [
    # /invite/<token>/, /sign/<token>/, /proposal/<token>/, /r/<token>/
    (re.compile(r"/(invite|sign|proposal|r)/[^/\s?\"']+"), r"/\1/" + REDACTED),
    (re.compile(r"/password/reset/key/[^/\s?\"']+"), "/password/reset/key/" + REDACTED),
    # Query values that are secrets: OAuth codes and states, tokens, keys.
    (
        re.compile(r"([?&](?:code|state|token|key|signature)=)[^&\s\"']+", re.IGNORECASE),
        r"\1" + REDACTED,
    ),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactFilter(logging.Filter):
    """Rewrites each record's message with tokens taken out."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not stop logging
            message = str(record.msg)
        cleaned = redact(message)
        if cleaned != message or record.args:
            record.msg, record.args = cleaned, None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for the host's log viewer."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["error"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry)
