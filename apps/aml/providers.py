"""A small interface for a paid identity-check service. None is connected in the first version."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class CheckResult:
    passed: bool
    reference: str = ""
    detail: str = ""


class IdentityProvider(Protocol):
    name: str

    def start_check(self, *, full_name: str, email: str) -> str:
        """Begin an electronic check and return the provider's reference."""

    def result(self, reference: str) -> CheckResult:
        """The outcome of a check started earlier."""


def get_provider() -> IdentityProvider | None:
    """The configured provider. None until one is chosen and built."""
    return None
