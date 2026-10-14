"""Staff side of proposals: the list on the Engagement tab, compose, withdraw."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.clients.models import Client
from apps.clients.views_base import get_client
from apps.comms import services as comms
from apps.core.models import PracticeSettings
from apps.core.permissions import StaffRequiredMixin

from . import proposals
from .forms import ProposalComposeForm
from .models import Proposal


def tab_context(client: Client) -> dict:
    rows = list(client.proposals.select_related("contact", "message"))
    return {
        "proposals": rows,
        "has_proposal_draft": any(p.state == "draft" for p in rows),
        "proposal_services_changed": bool(rows)
        and rows[0].state in ("draft", "sent", "viewed")
        and proposals.services_changed_since(rows[0]),
        "proposal_starter": proposals.uses_starter_wording(),
        "can_propose": client.status in (Client.Status.PROSPECT, Client.Status.ONBOARDING)
        and client.client_services.filter(state="proposed").exists(),
    }


class ProposalMixin(StaffRequiredMixin):
    def proposal(self, pk, proposal_pk) -> Proposal:
        return get_object_or_404(Proposal, pk=proposal_pk, client_id=pk)


class ProposalCreateView(StaffRequiredMixin, View):
    def post(self, request, pk):
        client = get_client(pk)
        try:
            proposal = proposals.create_proposal(request.user, client)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("onboarding:engagement", pk=pk)
        return redirect("pipeline:proposal_send", pk=pk, proposal_pk=proposal.pk)


class ProposalDetailView(ProposalMixin, View):
    """A proposal as the client sees it, with what happened to it."""

    def get(self, request, pk, proposal_pk):
        proposal = self.proposal(pk, proposal_pk)
        context = {
            "client": proposal.client,
            "proposal": proposal,
            "body": proposals.render_body(proposal),
            "starter": proposals.uses_starter_wording(),
        }
        return render(request, "pipeline/proposal_detail.html", context)


class ProposalComposeView(ProposalMixin, View):
    """ "Send proposal": the compose window with the proposal email filled in."""

    def _form(self, request, proposal, data=None, files=None):
        client = proposal.client
        initial = {}
        if data is None:
            subject, html = proposals.default_message(proposal, request.user)
            practice = PracticeSettings.load()
            initial = {
                "subject": subject,
                "body": html,
                "cc": practice.email,
                "show_breakdown": proposal.show_breakdown,
                "show_inc_vat": proposal.show_inc_vat,
                "show_vat_text": proposal.show_vat_text,
            }
            if proposal.contact is not None and proposal.contact.email:
                initial["contacts"] = [proposal.contact.email]
        return ProposalComposeForm(data, files, initial=initial, client=client)

    def _render(self, request, proposal, form, status=200):
        context = {
            "client": proposal.client,
            "proposal": proposal,
            "form": form,
            "preview": proposals.render_body(proposal),
            "warning": comms.warning_for(proposal.client),
            "starter": proposals.uses_starter_wording(),
            "vat_registered": proposal.vat_rate is not None,
            "can_send_now": request.user.can("comms.approve"),
        }
        return render(request, "pipeline/proposal_compose.html", context, status=status)

    def get(self, request, pk, proposal_pk):
        proposal = self.proposal(pk, proposal_pk)
        if not proposal.is_editable:
            return redirect("pipeline:proposal", pk=pk, proposal_pk=proposal_pk)
        return self._render(request, proposal, self._form(request, proposal))

    def post(self, request, pk, proposal_pk):
        proposal = self.proposal(pk, proposal_pk)
        if not proposal.is_editable:
            raise Http404
        form = self._form(request, proposal, request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, proposal, form, 422)
        data = form.cleaned_data
        try:
            proposals.set_switches(
                proposal,
                show_breakdown=data["show_breakdown"],
                show_inc_vat=data["show_inc_vat"],
                show_vat_text=data["show_vat_text"],
            )
            if request.POST.get("action") == "refresh":
                # New switches change the figures in the message: rebuild it from the template.
                subject, html = proposals.default_message(proposal, request.user)
                bound = self._form(request, proposal)
                bound.initial.update(
                    {"contacts": data["contacts"], "cc": data["cc"], "signature": data["signature"]}
                )
                bound.initial.update({"subject": subject, "body": html})
                messages.info(request, "The message was rebuilt with the new fee settings.")
                return self._render(request, proposal, bound)
            documents = list(
                proposal.client.documents.filter(pk__in=data["attachments"], sensitive=False)
            )
            proposals.send_proposal(
                request.user,
                proposal,
                to=data["to"],
                cc=data["cc"],
                subject=data["subject"],
                body_html=data["body"],
                attachments=documents,
                uses_signature=data["signature"] == "mine",
            )
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
            return self._render(request, proposal, form, 422)
        proposal.refresh_from_db()
        if proposal.message is not None and proposal.message.state == "approved":
            messages.success(request, "The proposal is approved and will go out in a few minutes.")
        else:
            messages.success(
                request, "The proposal is queued and needs approval before it goes out."
            )
        return redirect("onboarding:engagement", pk=pk)


class ProposalActionView(ProposalMixin, View):
    action = ""

    def post(self, request, pk, proposal_pk):
        proposal = self.proposal(pk, proposal_pk)
        try:
            if self.action == "withdraw":
                proposals.withdraw(request.user, proposal)
                messages.success(
                    request, "The proposal was withdrawn and its link no longer works."
                )
            elif self.action == "cancel_link":
                count = proposals.cancel_link(request.user, proposal)
                messages.success(request, "The link was cancelled." if count else "No live link.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("onboarding:engagement", pk=pk)
