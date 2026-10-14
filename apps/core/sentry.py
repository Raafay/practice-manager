"""Scrubbing for the optional error reports (SENTRY_DSN). Nothing personal leaves.

The report keeps the error type, the stack of file names and line numbers, and the
address with its tokens taken out. Everything else that could hold personal data
(request data, cookies, headers, the user, local variables, log breadcrumbs) is
dropped before it is sent.
"""

from apps.core.logs import redact


def scrub_event(event, hint=None):
    request = event.get("request") or {}
    event["request"] = {
        "method": request.get("method", ""),
        "url": redact(request.get("url", "") or ""),
    }
    event.pop("user", None)
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    for exception in (event.get("exception") or {}).get("values", []) or []:
        # Error messages can quote a value (a database error naming a duplicate
        # email), so only the error's type is kept.
        exception["value"] = "(removed)"
        for frame in (exception.get("stacktrace") or {}).get("frames", []) or []:
            frame.pop("vars", None)
            frame.pop("context_line", None)
            frame.pop("pre_context", None)
            frame.pop("post_context", None)
    if "logentry" in event:
        entry = event["logentry"] or {}
        event["logentry"] = {"message": redact(str(entry.get("message", "")))[:200]}
    if "message" in event:
        event["message"] = redact(str(event["message"]))[:200]
    return event
