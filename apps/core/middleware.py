from django.conf import settings
from django.http import FileResponse, HttpResponse


class ContentSecurityPolicyMiddleware:
    """Send the Content-Security-Policy header on every response."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = settings.CONTENT_SECURITY_POLICY

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.policy)
        return response


class PrivateFileHeadersMiddleware:
    """Files are never cached by a shared cache or the browser, and never sniffed.

    Every file the app serves comes through a view that checked permission. A view
    that wants different caching (the practice logo) sets its own header first.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if isinstance(response, FileResponse):
            response.headers.setdefault("Cache-Control", "private, no-store")
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response


class RequestSizeLimitMiddleware:
    """Refuse a request body over the largest upload before anything reads it.

    Django reads a POST (and writes its files to disk) as soon as the CSRF check
    looks at it, so the per-file limits alone would come too late. The host's
    proxy should also cap the body size (docs/DEPLOY.md).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.limit = settings.MAX_REQUEST_BYTES

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > self.limit:
            return HttpResponse(
                "The upload is too large. Send fewer files at a time (25 MB at most each).",
                status=413,
                content_type="text/plain; charset=utf-8",
            )
        return self.get_response(request)
