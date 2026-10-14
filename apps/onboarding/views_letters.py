"""Staff side of engagement letters: the Engagement tab, preparing, editing and sending."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.clients.models import Contact
from apps.clients.views import ClientTabView
from apps.clients.views_base import get_client
from apps.core.permissions import CapabilityRequiredMixin

from . import letters
from .forms_letters import LetterForm
from .models import EngagementLetter


class EngagementTabView(ClientTabView):
    tab = "engagement"
    tab_template = "onboarding/tabs/_engagement.html"

    def context_engagement(self, request, client):
        from apps.pipeline.views_proposals import tab_context

        rows = list(client.engagement_letters.select_related("signer", "message"))
        return {
            **tab_context(client),
            "can_fees": request.user.can("fees.view"),
            "letters": rows,
            "has_draft": any(r.state == "draft" for r in rows),
            "services_changed": letters.services_changed_since_signed(client),
            "starter_wording": letters.uses_starter_wording(),
        }


class LetterMixin(CapabilityRequiredMixin):
    # An engagement letter lists the fees, so it needs the right to see fees.
    required_rights = ("fees.view",)

    def letter(self, pk, letter_pk) -> EngagementLetter:
        return get_object_or_404(EngagementLetter, pk=letter_pk, client_id=pk)


class PrepareView(LetterMixin, View):
    def post(self, request, pk):
        client = get_client(pk)
        try:
            letter = letters.prepare_letter(request.user, client)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("onboarding:engagement", pk=pk)
        return redirect("onboarding:letter", pk=pk, letter_pk=letter.pk)


class LetterView(LetterMixin, View):
    """Preview and edit a draft; show a sent or signed letter read-only."""

    def _render(self, request, letter, form=None, status=200):
        client = letter.client
        if form is None:
            form = LetterForm(
                initial={"signer": letter.signer_id, "body_html": letter.body_html},
                signers=Contact.objects.filter(
                    pk__in=[c.pk for c in letters.signer_choices(client)]
                ),
            )
        context = {
            "client": client,
            "letter": letter,
            "form": form,
            "problems": letters.blocking_problems(letter) if letter.is_editable else [],
            "starter_wording": letters.uses_starter_wording(),
        }
        return render(request, "onboarding/letter.html", context, status=status)

    def get(self, request, pk, letter_pk):
        return self._render(request, self.letter(pk, letter_pk))

    def post(self, request, pk, letter_pk):
        letter = self.letter(pk, letter_pk)
        if not letter.is_editable:
            raise Http404
        form = LetterForm(
            request.POST,
            signers=Contact.objects.filter(
                pk__in=[c.pk for c in letters.signer_choices(letter.client)]
            ),
        )
        if not form.is_valid():
            return self._render(request, letter, form, 422)
        try:
            letters.save_draft(
                request.user,
                letter,
                body_html=form.cleaned_data["body_html"],
                signer=form.cleaned_data["signer"],
            )
            if "send" in request.POST:
                letters.send_letter(request.user, letter)
                messages.success(
                    request,
                    "The letter is saved and the email is waiting in Queued for approval.",
                )
                return redirect("onboarding:engagement", pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, letter, form, 422)
        messages.success(request, "Letter saved.")
        return redirect("onboarding:letter", pk=pk, letter_pk=letter_pk)


class LetterActionView(LetterMixin, View):
    action = ""

    def post(self, request, pk, letter_pk):
        letter = self.letter(pk, letter_pk)
        try:
            if self.action == "cancel":
                letters.cancel_letter(request.user, letter)
                messages.success(request, "The letter was cancelled and its link no longer works.")
            elif self.action == "cancel_link":
                count = letters.cancel_signing_link(request.user, letter)
                messages.success(
                    request, "The signing link was cancelled." if count else "No live link."
                )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("onboarding:engagement", pk=pk)


class LetterPartsView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def get(self, request):
        from .models import LetterPart

        return render(
            request, "onboarding/settings_letter.html", {"parts": LetterPart.objects.all()}
        )


class LetterPartEditView(CapabilityRequiredMixin, View):
    required_rights = ("settings.manage",)

    def _part(self, key):
        from .models import LetterPart

        return get_object_or_404(LetterPart, key=key)

    def _render(self, request, part, form, status=200):
        grouped: dict[str, list] = {}
        from apps.comms import merge

        for name, (group, label) in merge.FIELDS.items():
            if not name.endswith("_link"):
                grouped.setdefault(group, []).append((name, label))
        return render(
            request,
            "onboarding/letter_part_form.html",
            {"part": part, "form": form, "field_groups": grouped},
            status=status,
        )

    def get(self, request, key):
        from .forms_letters import LetterPartForm

        part = self._part(key)
        return self._render(request, part, LetterPartForm(instance=part))

    def post(self, request, key):
        from apps import events
        from apps.core.html import clean_html

        from .forms_letters import LetterPartForm

        part = self._part(key)
        form = LetterPartForm(request.POST, instance=part)
        if not form.is_valid():
            return self._render(request, part, form, 422)
        part = form.save(commit=False)
        part.body = clean_html(part.body)
        part.starter = False
        part.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} changed the engagement letter part “{part}”.",
            setting="engagement letter",
        )
        messages.success(request, f"{part} saved.")
        return redirect("onboarding:letter_parts")
