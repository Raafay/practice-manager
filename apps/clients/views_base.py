from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from django.utils.cache import patch_vary_headers

from apps.core.htmx import htmx_redirect

from .models import Client


def wants_partial(request) -> bool:
    """True for an HTMX request that is not the browser restoring a page from history."""
    htmx = getattr(request, "htmx", False)
    return bool(htmx) and not htmx.history_restore_request


def respond(request, template: str, partial: str, context: dict, status: int = 200):
    """Full page or partial, and tell caches the answer depends on the HTMX header."""
    response = render(
        request, partial if wants_partial(request) else template, context, status=status
    )
    patch_vary_headers(response, ["HX-Request"])
    return response


def get_client(pk) -> Client:
    return get_object_or_404(Client, pk=pk)


def render_form(
    request,
    *,
    title,
    form,
    action,
    submit="Save",
    target="modal",
    status=200,
    intro="",
    danger=False,
    multipart=False,
    extra="",
    back="",
):
    """A form shown in a dialog for HTMX requests and on its own page otherwise."""
    context = {
        "title": title,
        "form": form,
        "action": action,
        "submit": submit,
        "target": target,
        "intro": intro,
        "danger": danger,
        "multipart": multipart,
        "extra_template": extra,
        "back": back,
    }
    return respond(request, "clients/form_page.html", "clients/_form_dialog.html", context, status)


def done(request, url: str, message: str = ""):
    if message:
        messages.success(request, message)
    return htmx_redirect(request, url)
