"""The client Risk tab: identity checks and risk assessments."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.permissions import StaffRequiredMixin

from . import services
from .forms import IdentityCheckForm, PersonAddForm, ReasonForm, SendBackForm
from .models import IdentityCheck, RiskAssessment


class RiskTabView(ClientTabView):
    tab = "risk"
    tab_template = "aml/tabs/_risk.html"

    def context_risk(self, request, client):
        services.sync_checks(client)
        state_key, state_label, state_tone = services.state_of(client)
        verified, total = services.identity_progress(client)
        reasons = {c.pk: r for c, r in services.proposed_people(client)}
        checks = list(services.listed_checks(client))
        for check in checks:
            check.reasons = reasons.get(check.contact_id) or (
                [f"Added by hand: {check.added_reason}"] if check.added_by_hand else []
            )
        return {
            "aml_state": (state_key, state_label, state_tone),
            "current": services.current_assessment(client),
            "open_assessment": services.open_assessment(client),
            "history": client.risk_assessments.all(),
            "checks": checks,
            "removed_checks": client.identity_checks.filter(excluded=True).select_related(
                "contact"
            ),
            "verified": verified,
            "total_people": total,
            "prompts": services.open_prompts(client),
            "can_see_sensitive": request.user.can("documents.sensitive"),
        }


class IdentityEditView(StaffRequiredMixin, View):
    def _check(self, pk, check_pk):
        return get_object_or_404(IdentityCheck, pk=check_pk, client_id=pk)

    def _render(self, request, check, form, status=200):
        return render_form(
            request,
            title=f"Identity: {check.contact.full_name}",
            form=form,
            action=reverse("aml:identity", args=[check.client_id, check.pk]),
            target="drawer",
            multipart=True,
            status=status,
            intro="Document numbers are not stored. Upload a copy: the upload is the record.",
        )

    def get(self, request, pk, check_pk):
        check = self._check(pk, check_pk)
        form = IdentityCheckForm(
            initial={
                "state": check.state,
                "method": check.method,
                "document_type": check.document_type,
                "document_expiry": check.document_expiry,
                "proof_of_address": check.proof_of_address,
                "notes": check.notes,
            }
        )
        return self._render(request, check, form)

    def post(self, request, pk, check_pk):
        check = self._check(pk, check_pk)
        if (request.FILES.get("id_file") or request.FILES.get("address_file")) and (
            not request.user.can("documents.sensitive")
        ):
            raise PermissionDenied
        form = IdentityCheckForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, check, form, 422)
        data = form.cleaned_data
        try:
            if data["id_file"]:
                services.upload_for_check(request.user, check, data["id_file"])
            if data["address_file"]:
                services.upload_for_check(
                    request.user, check, data["address_file"], proof_of_address=True
                )
            services.update_check(
                request.user,
                check,
                {
                    k: data[k]
                    for k in (
                        "state",
                        "method",
                        "document_type",
                        "document_expiry",
                        "proof_of_address",
                        "notes",
                    )
                },
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, check, form, 422)
        return done(request, reverse("aml:tab", args=[pk]))


class PersonAddView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title="Add a person to identify",
            form=form,
            action=reverse("aml:person_add", args=[client.pk]),
            submit="Add",
            status=status,
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, PersonAddForm(client=client))

    def post(self, request, pk):
        client = get_client(pk)
        form = PersonAddForm(request.POST, client=client)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        try:
            services.add_person(
                request.user, client, form.cleaned_data["contact"], form.cleaned_data["reason"]
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, client, form, 422)
        return done(request, reverse("aml:tab", args=[pk]))


class PersonRemoveView(StaffRequiredMixin, View):
    def _render(self, request, check, form, status=200):
        return render_form(
            request,
            title=f"Take {check.contact.full_name} off the list",
            form=form,
            action=reverse("aml:person_remove", args=[check.client_id, check.pk]),
            submit="Take off the list",
            danger=True,
            status=status,
            intro="Give the reason. It is kept with the AML records.",
        )

    def get(self, request, pk, check_pk):
        check = get_object_or_404(IdentityCheck, pk=check_pk, client_id=pk)
        return self._render(request, check, ReasonForm())

    def post(self, request, pk, check_pk):
        check = get_object_or_404(IdentityCheck, pk=check_pk, client_id=pk)
        form = ReasonForm(request.POST)
        if not form.is_valid():
            return self._render(request, check, form, 422)
        try:
            services.remove_person(request.user, check, form.cleaned_data["reason"])
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, check, form, 422)
        return done(request, reverse("aml:tab", args=[pk]))


# ------------------------------------------------------------------ assessments


class AssessmentStartView(StaffRequiredMixin, View):
    def post(self, request, pk):
        client = get_client(pk)
        reason = request.POST.get("reason", "")[:300]
        assessment = services.start_assessment(request.user, client, reason)
        return redirect("aml:assessment", pk=pk, assessment_pk=assessment.pk)


def _sections(assessment):
    """Active questions grouped by section, with the answer given so far."""
    sections: dict[str, list] = {}
    for question in services.active_questions():
        entry = assessment.answers.get(str(question.pk)) or {}
        sections.setdefault(question.section, []).append((question, entry))
    return list(sections.items())


class AssessmentView(StaffRequiredMixin, View):
    def _assessment(self, pk, assessment_pk):
        return get_object_or_404(RiskAssessment, pk=assessment_pk, client_id=pk)

    def _render(self, request, assessment, problems=(), status=200):
        approve_ok, approve_why = services.can_approve(request.user, assessment)
        context = {
            "client": assessment.client,
            "assessment": assessment,
            "sections": _sections(assessment),
            "problems": list(problems),
            "levels": [("low", "Low"), ("medium", "Medium"), ("high", "High")],
            "can_approve": assessment.state == "submitted" and approve_ok,
            "approve_why": approve_why if assessment.state == "submitted" else "",
            "may_approve_right": request.user.can("aml.approve"),
            "today": timezone.localdate(),
            "answers_view": [
                e for _, e in sorted(assessment.answers.items(), key=lambda kv: int(kv[0]))
            ],
        }
        return render(request, "aml/assessment.html", context, status=status)

    def get(self, request, pk, assessment_pk):
        return self._render(request, self._assessment(pk, assessment_pk))

    def post(self, request, pk, assessment_pk):
        assessment = self._assessment(pk, assessment_pk)
        if not assessment.is_editable:
            raise PermissionDenied
        submit = "submit" in request.POST
        try:
            problems = services.save_draft(request.user, assessment, request.POST, submit=submit)
        except ValidationError as error:
            problems = error.messages
        if problems:
            return self._render(request, assessment, problems, status=422)
        if submit:
            messages.success(request, "Submitted for approval.")
            return redirect("aml:tab", pk=pk)
        messages.success(request, "Draft saved.")
        return redirect("aml:assessment", pk=pk, assessment_pk=assessment_pk)


class AssessmentApproveView(StaffRequiredMixin, View):
    def post(self, request, pk, assessment_pk):
        assessment = get_object_or_404(RiskAssessment, pk=assessment_pk, client_id=pk)
        try:
            services.approve(request.user, assessment)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("aml:assessment", pk=pk, assessment_pk=assessment_pk)
        messages.success(request, "Approved.")
        return redirect("aml:tab", pk=pk)


class AssessmentSendBackView(StaffRequiredMixin, View):
    def _render(self, request, assessment, form, status=200):
        return render_form(
            request,
            title="Send back to the assessor",
            form=form,
            action=reverse("aml:send_back", args=[assessment.client_id, assessment.pk]),
            submit="Send back",
            status=status,
        )

    def get(self, request, pk, assessment_pk):
        assessment = get_object_or_404(RiskAssessment, pk=assessment_pk, client_id=pk)
        if not request.user.can("aml.approve"):
            raise PermissionDenied
        return self._render(request, assessment, SendBackForm())

    def post(self, request, pk, assessment_pk):
        assessment = get_object_or_404(RiskAssessment, pk=assessment_pk, client_id=pk)
        form = SendBackForm(request.POST)
        if not form.is_valid():
            return self._render(request, assessment, form, 422)
        try:
            services.send_back(request.user, assessment, form.cleaned_data["reason"])
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, assessment, form, 422)
        return done(request, reverse("aml:tab", args=[pk]), "Sent back.")
