from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View

from apps.clients.views_base import done, get_client, render_form
from apps.core.permissions import StaffRequiredMixin

from . import clearance
from .forms import ClearanceForm, ClearanceUpdateForm
from .models import ClearanceRequest


class ClearanceStartView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title="Ask the previous accountant for clearance",
            form=form,
            action=reverse("onboarding:clearance_start", args=[client.pk]),
            submit="Queue the request",
            target="drawer",
            status=status,
            intro="This makes a letter and an email. The email waits in Queued until someone "
            "approves it.",
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, ClearanceForm())

    def post(self, request, pk):
        client = get_client(pk)
        form = ClearanceForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        try:
            clearance.start(
                request.user,
                client,
                accountant_name=data["accountant_name"],
                email=data["email"],
                firm=data["firm"],
                asked_for=data["asked_for"],
                notes=data["notes"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, client, form, 422)
        return done(request, reverse("onboarding:tab", args=[pk]), "Queued for approval.")


class ClearanceUpdateView(StaffRequiredMixin, View):
    def _req(self, pk, req_pk):
        return get_object_or_404(ClearanceRequest, pk=req_pk, client_id=pk)

    def _render(self, request, req, form, status=200):
        return render_form(
            request,
            title=f"Clearance from {req.accountant_name}",
            form=form,
            action=reverse("onboarding:clearance_update", args=[req.client_id, req.pk]),
            target="drawer",
            status=status,
        )

    def get(self, request, pk, req_pk):
        req = self._req(pk, req_pk)
        form = ClearanceUpdateForm(
            initial={
                "received": req.received,
                "reply_received_on": req.reply_received_on,
                "notes": req.notes,
            }
        )
        return self._render(request, req, form)

    def post(self, request, pk, req_pk):
        req = self._req(pk, req_pk)
        form = ClearanceUpdateForm(request.POST)
        if not form.is_valid():
            return self._render(request, req, form, 422)
        data = form.cleaned_data
        clearance.update(
            request.user,
            req,
            received=data["received"],
            reply_received_on=data["reply_received_on"],
            notes=data["notes"],
        )
        return done(request, reverse("onboarding:tab", args=[pk]))


class ClearanceChaseView(StaffRequiredMixin, View):
    def post(self, request, pk, req_pk):
        req = get_object_or_404(ClearanceRequest, pk=req_pk, client_id=pk)
        try:
            clearance.chase(request.user, req)
            messages.success(request, "Chase queued for approval.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("onboarding:tab", pk=pk)
