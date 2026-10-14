"""The signing page. No sign-in: a private link for one person, one letter, one signature."""

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views import View

from apps.core import actionlinks, ratelimit
from apps.core.models import ActionLink
from apps.events.middleware import request_ip

from . import letters
from .forms_letters import SignForm
from .models import EngagementLetter


def _no_index(response):
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


class SignMixin:
    def load(self, token):
        link = actionlinks.resolve(token, ActionLink.Purpose.SIGN_LETTER)
        if link is None:
            raise Http404
        letter = EngagementLetter.objects.filter(pk=link.object_id, client=link.client).first()
        if letter is None or letter.state in ("draft", "cancelled", "replaced"):
            raise Http404
        return link, letter


class SignView(SignMixin, View):
    def _render(self, request, link, letter, form, error="", status=200):
        context = {
            "link": link,
            "letter": letter,
            "form": form,
            "token": request.resolver_match.kwargs["token"],
            "error": error,
            "signed": letter.state == "signed",
            "client_name": letter.client.name,
        }
        return _no_index(render(request, "onboarding/sign.html", context, status=status))

    def get(self, request, token):
        link, letter = self.load(token)
        if letter.state in ("sent", "viewed"):
            letters.note_viewed(letter, link)
        return self._render(request, link, letter, SignForm())

    def post(self, request, token):
        link, letter = self.load(token)
        ip = request_ip(request) or ""
        if not ratelimit.hit(f"sign-ip:{ip}", 10, 3600) or not ratelimit.hit(
            f"sign-token:{token}", 30, 86400
        ):
            return _no_index(render(request, "onboarding/sign_limited.html", status=429))
        form = SignForm(request.POST)
        if not form.is_valid():
            return self._render(request, link, letter, form, status=422)
        try:
            letters.sign_letter(
                link,
                typed_name=form.cleaned_data["typed_name"],
                agreed=form.cleaned_data["agree"],
                ip=ip or None,
                agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except ValidationError as error:
            letter.refresh_from_db()
            return self._render(
                request, link, letter, form, error=" ".join(error.messages), status=422
            )
        letter.refresh_from_db()
        return self._render(request, link, letter, SignForm())


class SignPdfView(SignMixin, View):
    def get(self, request, token):
        link, letter = self.load(token)
        document = letter.signed_document if letter.state == "signed" else letter.unsigned_document
        if document is None or document.deleted_at:
            raise Http404
        response = FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=f"Engagement letter v{letter.version}.pdf",
            content_type="application/pdf",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return _no_index(response)
