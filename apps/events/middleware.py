from .context import RequestInfo, reset, set_current


def request_ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR") or None


class RequestContextMiddleware:
    """Keep the current user and address for `events.record` while a request runs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current(
            RequestInfo(
                user=getattr(request, "user", None),
                ip_address=request_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            )
        )
        try:
            return self.get_response(request)
        finally:
            reset(token)
