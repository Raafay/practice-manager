from django.http import HttpResponse
from django.shortcuts import redirect


class HtmxTemplateMixin:
    """Render `partial_template_name` for HTMX requests and `template_name` otherwise."""

    partial_template_name: str | None = None

    def get_template_names(self):
        if getattr(self.request, "htmx", False) and self.partial_template_name:
            return [self.partial_template_name]
        return super().get_template_names()


def htmx_redirect(request, url: str):
    """Send the browser to url, as a full page load when the request came from HTMX."""
    if getattr(request, "htmx", False):
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect(url)
