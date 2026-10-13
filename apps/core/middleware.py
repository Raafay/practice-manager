from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Send the Content-Security-Policy header on every response."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = settings.CONTENT_SECURITY_POLICY

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.policy)
        return response
