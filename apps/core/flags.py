"""Settings that the owner can change while the site runs.

A third-party library reads some settings with a plain truth test (for example
allauth's MFA_TRUST_ENABLED). PracticeFlag answers that test from the Practice
settings row, so a switch in Settings takes effect without a restart.
"""

from django.db.utils import OperationalError, ProgrammingError


class PracticeFlag:
    def __init__(self, field: str, default: bool):
        self.field = field
        self.default = default

    def __bool__(self) -> bool:
        from apps.core.models import PracticeSettings

        try:
            return bool(getattr(PracticeSettings.load(), self.field))
        except (OperationalError, ProgrammingError, RuntimeError):
            # No table yet (first migrate), or no database access at all (a
            # library reading the flag while URLs are imported under the test runner).
            return self.default

    def __repr__(self) -> str:
        return f"PracticeFlag({self.field!r})"
