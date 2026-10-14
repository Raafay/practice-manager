"""The proposal page. No sign-in: a private link for one person and one proposal."""

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views import View

from apps.core import actionlinks, ratelimit
from apps.core.models import ActionLink
from apps.events.middleware import request_ip

from . import proposals
from .forms import AcceptForm, DeclineForm, QuestionForm
from .models import Proposal

DECIDED = ("accepted", "declined", "expired", "withdrawn")


def _no_index(response):
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


def unavailable(request):
    """The same plain message for a wrong, expired or cancelled link, so nothing is revealed."""
    return _no_index(render(request, "pipeline/proposal_unavailable.html", status=404))


class ProposalLinkMixin:
    def load(self, token):
        link = actionlinks.resolve(token, ActionLink.Purpose.PROPOSAL)
        if link is None:
            raise Http404
        proposal = Proposal.objects.filter(pk=link.object_id, client=link.client).first()
        if proposal is None or proposal.state in ("draft", "withdrawn"):
            raise Http404
        return link, proposal

    def handle_exception(self, exc):  # pragma: no cover - Django handles Http404 via dispatch
        raise exc

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except Http404:
            return unavailable(request)


class ProposalPageView(ProposalLinkMixin, View):
    def _render(self, request, link, proposal, *, forms=None, error="", status=200, notice=""):
        forms = forms or {}
        decided = proposal.state in DECIDED
        context = {
            "proposal": proposal,
            "client_name": proposal.client.name,
            "body": proposals.render_body(proposal),
            "token": request.resolver_match.kwargs["token"],
            "accept_form": forms.get("accept") or AcceptForm(),
            "decline_form": forms.get("decline") or DeclineForm(),
            "question_form": forms.get("question") or QuestionForm(),
            "error": error,
            "notice": notice,
            "decided": decided,
            "open_form": forms.get("open", ""),
        }
        return _no_index(render(request, "pipeline/proposal_page.html", context, status=status))

    def get(self, request, token):
        link, proposal = self.load(token)
        if proposal.state in ("sent", "viewed"):
            proposals.note_viewed(proposal, link)
            proposal.refresh_from_db()
        return self._render(request, link, proposal)

    def post(self, request, token):
        link, proposal = self.load(token)
        ip = request_ip(request) or ""
        if not ratelimit.hit(f"proposal-ip:{ip}", 10, 3600) or not ratelimit.hit(
            f"proposal-token:{token}", 30, 86400
        ):
            return _no_index(render(request, "pipeline/proposal_limited.html", status=429))
        action = request.POST.get("action", "")
        agent = request.META.get("HTTP_USER_AGENT", "")
        try:
            if action == "accept":
                form = AcceptForm(request.POST)
                if not form.is_valid():
                    return self._render(
                        request,
                        link,
                        proposal,
                        forms={"accept": form, "open": "accept"},
                        status=422,
                    )
                proposals.accept(
                    link,
                    typed_name=form.cleaned_data["typed_name"],
                    agreed=form.cleaned_data["agree"],
                    ip=ip or None,
                    agent=agent,
                )
            elif action == "decline":
                form = DeclineForm(request.POST)
                form.is_valid()
                proposals.decline(
                    link, reason=form.cleaned_data.get("reason", ""), ip=ip or None, agent=agent
                )
            elif action == "question":
                form = QuestionForm(request.POST)
                if not form.is_valid():
                    return self._render(
                        request,
                        link,
                        proposal,
                        forms={"question": form, "open": "question"},
                        status=422,
                    )
                proposals.ask_question(link, text=form.cleaned_data["question"])
                proposal.refresh_from_db()
                return self._render(
                    request,
                    link,
                    proposal,
                    notice="Thank you. We have your question and will reply by email.",
                )
            else:
                raise Http404
        except ValidationError as error:
            proposal.refresh_from_db()
            return self._render(request, link, proposal, error=" ".join(error.messages), status=422)
        proposal.refresh_from_db()
        return self._render(request, link, proposal)


class ProposalPdfView(ProposalLinkMixin, View):
    def get(self, request, token):
        link, proposal = self.load(token)
        document = proposal.accepted_document if proposal.state == "accepted" else proposal.document
        document = document or proposal.document
        if document is None or document.deleted_at:
            raise Http404
        response = FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=f"Proposal v{proposal.version}.pdf",
            content_type="application/pdf",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return _no_index(response)
