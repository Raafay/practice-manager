"""Overview panel: prospects that have gone quiet."""

from . import services

LIMIT = 8


def overview_context(user) -> dict:
    rows = [
        {"details": d, "reason": services.quiet_reason(d)} for d in services.quiet_prospects(user)
    ]
    return {"quiet_rows": rows[:LIMIT], "quiet_total": len(rows)}
