"""The request link: /r/<token>/. No sign-in. Shows the client's name and nothing else."""

from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View

from apps import events
from apps.core import ratelimit
from apps.events.middleware import request_ip

from . import requests as request_services
from .access import no_index
from .forms import PublicRequestForm
from .models import Request


def unavailable(request):
    """The same plain page for a wrong, replaced or empty link, so nothing is revealed."""
    return no_index(render(request, "portal/request_unavailable.html", status=404))


class RequestFormView(View):
    def _page(self, request, client, form, *, status=200, error=""):
        return no_index(
            render(
                request,
                "portal/request_form.html",
                {"client_name": client.name, "form": form, "error": error},
                status=status,
            )
        )

    def get(self, request, token):
        client = request_services.client_for_token(token)
        if client is None:
            return unavailable(request)
        return self._page(request, client, PublicRequestForm())

    def post(self, request, token):
        client = request_services.client_for_token(token)
        if client is None:
            return unavailable(request)
        ip = request_ip(request) or ""
        # 10 submissions an hour per address, 30 a day per link (spec 01 section 5).
        if not ratelimit.hit(f"request-ip:{ip}", 10, 3600) or not ratelimit.hit(
            f"request-token:{token}", 30, 86400
        ):
            return no_index(render(request, "portal/request_limited.html", status=429))
        form = PublicRequestForm(request.POST)
        if not form.is_valid():
            return self._page(request, client, form, status=422)
        if form.cleaned_data["website"]:
            # A bot filled the hidden field. Look like success; keep nothing.
            events.record(
                None,
                "request.bot_trapped",
                f"A submission to the request link for {client.name} was dropped as a bot.",
                client=client,
                request=request,
            )
            return redirect("portal:request_thanks", token=token)
        try:
            obj = request_services.create_request(
                channel=Request.Channel.FORM,
                client=client,
                sender_name=form.cleaned_data["name"],
                sender_email=form.cleaned_data["email"],
                sender_phone=form.cleaned_data["phone"],
                body=form.cleaned_data["body"],
                urgency=form.cleaned_data["urgency"],
                uploads=request.FILES.getlist("files"),
                ip=ip or None,
            )
        except ValidationError as error:
            return self._page(request, client, form, status=422, error=" ".join(error.messages))
        return redirect(f"{request.path.rstrip('/')}/thanks/?ref={obj.reference}")


class RequestThanksView(View):
    def get(self, request, token):
        client = request_services.client_for_token(token)
        if client is None:
            return unavailable(request)
        reference = request.GET.get("ref", "")[:12]
        if not (reference[:1] == "R" and reference[1:].isdigit()):
            reference = ""
        return no_index(
            render(
                request,
                "portal/request_thanks.html",
                {"client_name": client.name, "reference": reference},
            )
        )
