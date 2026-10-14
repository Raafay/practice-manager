"""Staff side on a client: invite to the portal, the Requests tab, items, form review."""

import segno
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.clients.models import Client, ClientContact, Document
from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.forms import StyledFormMixin
from apps.core.permissions import StaffRequiredMixin
from apps.core.siteurl import absolute
from apps.tasks.models import Task

from . import pforms, services
from . import requests as request_services
from .models import PortalForm, PortalItem


class ClientRequestsView(ClientTabView):
    tab = "requests"
    tab_template = "portal/tabs/_requests.html"

    def context_requests(self, request, client):
        path = request_services.link_path(client)
        url = absolute(path)
        qr = segno.make(url, error="m").svg_inline(scale=4, border=2, dark="#0f172a", omitsize=True)
        return {
            "requests": client.requests.select_related("task").order_by("-received_at")[:100],
            "request_url": url,
            "request_qr": qr,
            "portal_items": client.portal_items.select_related("contact").order_by("-created_at")[
                :20
            ],
        }


class InviteView(StaffRequiredMixin, View):
    def post(self, request, pk, link_pk):
        client = get_client(pk)
        link = get_object_or_404(ClientContact, pk=link_pk, client=client)
        try:
            services.invite(request.user, link)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"{link.contact.full_name} was emailed the portal address.")
        return done(request, reverse("clients:contacts", args=[client.pk]))


class WithdrawView(StaffRequiredMixin, View):
    def post(self, request, pk, link_pk):
        client = get_client(pk)
        link = get_object_or_404(ClientContact, pk=link_pk, client=client)
        services.withdraw(request.user, link)
        messages.success(
            request, f"{link.contact.full_name} can no longer open this client's portal."
        )
        return done(request, reverse("clients:contacts", args=[client.pk]))


class ReplaceLinkView(StaffRequiredMixin, View):
    def post(self, request, pk):
        client = get_client(pk)
        request_services.replace_token(request.user, client)
        messages.success(request, "The request link was replaced. The old one no longer works.")
        return done(request, reverse("portal:client_requests", args=[client.pk]))


class CancelItemView(StaffRequiredMixin, View):
    def post(self, request, pk, item_pk):
        client = get_client(pk)
        item = get_object_or_404(PortalItem, pk=item_pk, client=client)
        services.cancel_item(request.user, item)
        return done(request, reverse("portal:client_requests", args=[client.pk]), "Withdrawn.")


# ---------------------------------------------------------------- from a task


def _portal_contact(client: Client):
    """Who the item is for: the main contact if they have portal access, else anyone."""
    main = client.client_contacts.filter(is_main=True, portal_access=True).first()
    return main.contact if main else None


class AskUploadView(StaffRequiredMixin, View):
    """“Ask the client to upload”: a thing to do on the portal, tied to this task."""

    def post(self, request, pk):
        task = get_object_or_404(Task.objects.select_related("client"), pk=pk)
        if task.client is None:
            messages.error(request, "This task has no client.")
        elif not task.client.client_contacts.filter(portal_access=True).exists():
            messages.error(
                request, "Nobody at this client has portal access yet. Invite them first."
            )
        else:
            services.create_item(
                request.user,
                task.client,
                PortalItem.Kind.UPLOAD_RECORDS,
                f"Upload records: {task.title}"[:200],
                contact=None,
                task=task,
                due_date=task.target_date,
            )
            messages.success(request, "Added to the client's portal as something to do.")
        return done(request, reverse("tasks:detail", args=[task.pk]))


class ApproveChoiceForm(StyledFormMixin, forms.Form):
    document = forms.ModelChoiceField(queryset=Document.objects.none(), label="Document")

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document"].queryset = Document.objects.live().filter(
            client=client, sensitive=False
        )


class AskApproveView(StaffRequiredMixin, View):
    """“Ask the client to approve this document”."""

    def _render(self, request, task, form, status=200):
        return render_form(
            request,
            title="Ask the client to approve a document",
            form=form,
            action=reverse("portal:task_ask_approve", args=[task.pk]),
            submit="Ask for approval",
            status=status,
            intro="The client reads it on their portal, ticks a box and types their name.",
            back=reverse("tasks:detail", args=[task.pk]),
        )

    def get(self, request, pk):
        task = get_object_or_404(Task.objects.select_related("client"), pk=pk)
        if task.client is None:
            return redirect("tasks:detail", pk=task.pk)
        return self._render(request, task, ApproveChoiceForm(client=task.client))

    def post(self, request, pk):
        task = get_object_or_404(Task.objects.select_related("client"), pk=pk)
        if task.client is None:
            return redirect("tasks:detail", pk=task.pk)
        form = ApproveChoiceForm(request.POST, client=task.client)
        if not form.is_valid():
            return self._render(request, task, form, 422)
        document = form.cleaned_data["document"]
        services.create_item(
            request.user,
            task.client,
            PortalItem.Kind.APPROVE_DOCUMENT,
            f"Please read and approve: {document.title}"[:200],
            contact=_portal_contact(task.client),
            object_id=document.pk,
            task=task,
            due_date=task.target_date,
        )
        document.shared_with_portal = True
        document.save(update_fields=["shared_with_portal", "updated_at"])
        return done(
            request, reverse("tasks:detail", args=[task.pk]), "Added to the client's portal."
        )


# ---------------------------------------------------------------- reviewing a form


class FormReviewView(StaffRequiredMixin, View):
    def _form(self, pk) -> PortalForm:
        return get_object_or_404(
            PortalForm.objects.select_related("client", "item", "document"), pk=pk
        )

    def get(self, request, pk):
        form = self._form(pk)
        context = {"pform": form, "client": form.client}
        if form.kind == PortalForm.Kind.CONFIRMATION:
            context["sections"] = [
                (s, form.answers.get(s.key, {})) for s in pforms.sections_for(form)
            ]
        else:
            context["rows"] = pforms.review_rows(form)
        return render(request, "portal/review.html", context)


class FormReviewActionView(StaffRequiredMixin, View):
    def post(self, request, pk):
        form = get_object_or_404(PortalForm.objects.select_related("client"), pk=pk)
        action = request.POST.get("action", "")
        key = request.POST.get("key", "")
        try:
            if action == "apply":
                pforms.apply_field(request.user, form, key)
            elif action == "dismiss":
                pforms.dismiss_field(request.user, form, key)
            elif action == "apply_all":
                pforms.apply_all(request.user, form)
            elif action == "dismiss_rest":
                pforms.dismiss_rest(request.user, form)
            else:
                raise ValidationError("Unknown action.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("portal:review", pk=pk)
