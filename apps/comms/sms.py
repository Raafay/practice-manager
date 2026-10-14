"""Text messages sit behind a small interface. No provider is included yet.

Set `SMS_BACKEND` to a dotted class path to switch texts on. Until then the
"Send SMS" button and text schedules are hidden.
"""

import logging
from importlib import import_module

from django.conf import settings

logger = logging.getLogger("apps.comms.sms")


class SmsBackend:
    def send(self, to: str, text: str) -> str:
        """Send one text. Return the provider's message id, or raise."""
        raise NotImplementedError


class ConsoleSmsBackend(SmsBackend):
    """Writes the text to the log. For development."""

    def send(self, to: str, text: str) -> str:
        logger.info("SMS to %s: %s", to, text)
        return "console"


class MemorySmsBackend(SmsBackend):
    """Keeps texts in a list. For tests."""

    outbox: list = []

    def send(self, to: str, text: str) -> str:
        self.outbox.append((to, text))
        return f"memory-{len(self.outbox)}"


def get_backend() -> SmsBackend | None:
    path = getattr(settings, "SMS_BACKEND", "")
    if not path:
        return None
    module, _, name = path.rpartition(".")
    return getattr(import_module(module), name)()


def sms_enabled() -> bool:
    return bool(getattr(settings, "SMS_BACKEND", ""))
