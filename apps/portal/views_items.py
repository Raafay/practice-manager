"""One thing to do: open it, finish it. Every item is looked up by public_id for this person."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.core import actionlinks, ratelimit
from apps.core.models import ActionLink
from apps.onboarding.models import EngagementLetter
from apps.pipeline.models import Proposal

from . import pforms, services
from .models import PortalForm, PortalItem
from .views import PortalView


class ItemMixin(PortalView):
    def get_item(self, request, public_id) -> PortalItem:
        return get_object_or_404(
            PortalItem.objects.for_portal_user(request.user).select_related("client", "task"),
            public_id=public_id,
        )


class ItemView(ItemMixin):
    """Open an item. Signing and proposals reuse the public pages through a short-lived link."""

    template = "portal/item.html"

    def get(self, request, public_id):
        item = self.get_item(request, public_id)
        if item.client_id != request.portal_client.pk:
            # The item is for another business of this person: switch to it.
            from .access import SESSION_CLIENT

            request.session[SESSION_CLIENT] = str(item.client.public_id)
            return redirect("portal:item", public_id=item.public_id)
        if item.state != PortalItem.State.OPEN:
            return self.page(request, {"item": item})
        handler = getattr(self, f"open_{item.kind}")
        return handler(request, item)

    def open_sign_letter(self, request, item):
        letter = EngagementLetter.objects.filter(pk=item.object_id, client=item.client).first()
        if letter is None or letter.state in ("draft", "cancelled", "replaced"):
            services.cancel_item(None, item)
            raise Http404
        if letter.state == "signed":
            services.complete_item(item, request.portal_contact, actor=request.user)
            return self.page(request, {"item": item})
        if not self._may_sign(request, letter):
            return self.page(
                request,
                {"item": item, "problem": "Please ask the person named on the letter to sign it."},
            )
        link, token = actionlinks.create(
            purpose=ActionLink.Purpose.SIGN_LETTER,
            contact=request.portal_contact,
            client=item.client,
            object_id=letter.pk,
            days=1,
        )
        return redirect(reverse("onboarding:sign", args=[token]))

    def _may_sign(self, request, letter) -> bool:
        contact = request.portal_contact
        if contact is None:
            return False
        if letter.signer_id == contact.pk:
            return True
        return contact.client_links.filter(client=letter.client, can_sign=True).exists()

    def open_accept_proposal(self, request, item):
        proposal = Proposal.objects.filter(pk=item.object_id, client=item.client).first()
        if proposal is None or proposal.state in ("draft", "withdrawn"):
            services.cancel_item(None, item)
            raise Http404
        if proposal.state in ("accepted", "declined", "expired"):
            services.complete_item(item, request.portal_contact, actor=request.user)
            return self.page(request, {"item": item})
        link, token = actionlinks.create(
            purpose=ActionLink.Purpose.PROPOSAL,
            contact=request.portal_contact,
            client=item.client,
            object_id=proposal.pk,
            days=1,
        )
        return redirect(reverse("pipeline:proposal_page", args=[token]))

    def open_upload_records(self, request, item):
        return self.page(request, {"item": item, "uploading": True, **self._upload_context()})

    def _upload_context(self):
        from .forms import UploadForm

        return {"form": UploadForm()}

    def open_confirm_details(self, request, item):
        return redirect("portal:form", public_id=item.public_id)

    open_client_details = open_confirm_details

    def open_approve_document(self, request, item):
        document = services.item_document(item)
        if document is None:
            services.cancel_item(None, item)
            raise Http404
        from apps.onboarding.forms_letters import SignForm

        return self.page(
            request,
            {"item": item, "document": document, "approve_form": SignForm(), "approving": True},
        )


class ItemUploadView(ItemMixin):
    """Upload against an "upload records" item."""

    def post(self, request, public_id):
        from .forms import UploadForm

        item = self.get_item(request, public_id)
        if item.kind != PortalItem.Kind.UPLOAD_RECORDS or not item.is_open:
            raise Http404
        form = UploadForm(request.POST)
        if form.is_valid():
            try:
                documents = services.upload_many(
                    request.user,
                    item.client,
                    request.FILES.getlist("files"),
                    category=form.cleaned_data["category"],
                    note=form.cleaned_data["note"],
                    task=item.task,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(
                    request,
                    f"Thank you. We received {len(documents)} file"
                    f"{'s' if len(documents) != 1 else ''}. "
                    "Press “That is everything” when you have sent it all.",
                )
                return redirect("portal:item", public_id=item.public_id)
        return self.page(
            request,
            {"item": item, "uploading": True, "form": form},
            status=422,
            template="portal/item.html",
        )


class EverythingView(ItemMixin):
    def post(self, request, public_id):
        item = self.get_item(request, public_id)
        if item.kind != PortalItem.Kind.UPLOAD_RECORDS:
            raise Http404
        services.everything_uploaded(item, request.user)
        messages.success(request, "Thank you. We will take it from here.")
        return redirect("portal:home")


class ApproveView(ItemMixin):
    def post(self, request, public_id):
        from apps.onboarding.forms_letters import SignForm

        item = self.get_item(request, public_id)
        if item.kind != PortalItem.Kind.APPROVE_DOCUMENT:
            raise Http404
        ip = request.META.get("REMOTE_ADDR", "")
        if not ratelimit.hit(f"portal-approve:{request.user.pk}", 20, 3600):
            raise Http404
        form = SignForm(request.POST)
        context = {
            "item": item,
            "document": services.item_document(item),
            "approve_form": form,
            "approving": True,
        }
        if not form.is_valid():
            return self.page(request, context, status=422, template="portal/item.html")
        try:
            services.approve_document(
                item,
                request.user,
                typed_name=form.cleaned_data["typed_name"],
                agreed=form.cleaned_data["agree"],
                ip=ip or None,
                agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except ValidationError as error:
            context["error"] = " ".join(error.messages)
            return self.page(request, context, status=422, template="portal/item.html")
        messages.success(request, "Thank you. Your approval is recorded.")
        return redirect("portal:home")


class ItemFormView(ItemMixin):
    """The confirmation statement check and the client details form."""

    template = "portal/form.html"

    def _item(self, request, public_id):
        item = self.get_item(request, public_id)
        if item.kind not in (PortalItem.Kind.CONFIRM_DETAILS, PortalItem.Kind.CLIENT_DETAILS):
            raise Http404
        return item

    def _context(self, form, errors=None, values=None, note=""):
        sections = pforms.sections_for(form, self.request.portal_contact)
        answers = values if values is not None else form.answers
        return {
            "item": form.item,
            "pform": form,
            "sections": sections,
            "answers": answers,
            "errors": errors or {},
            "is_confirmation": form.kind == PortalForm.Kind.CONFIRMATION,
            "locked": form.state != PortalForm.State.DRAFT,
            "note": note,
        }

    def get(self, request, public_id):
        item = self._item(request, public_id)
        form = pforms.form_for(item)
        return self.page(request, self._context(form))

    def post(self, request, public_id):
        item = self._item(request, public_id)
        form = pforms.form_for(item)
        if form.state != PortalForm.State.DRAFT:
            return self.page(request, self._context(form), status=409)
        answers = pforms.read_answers(form, request.POST)
        if "save" in request.POST:
            pforms.save_draft(form, answers)
            messages.success(request, "Saved. You can come back to finish it later.")
            return redirect("portal:form", public_id=item.public_id)
        errors = pforms.check_complete(form, answers)
        if errors:
            pforms.save_draft(form, answers)
            return self.page(
                request, self._context(form, errors=errors, values=answers), status=422
            )
        pforms.submit(form, answers, request.user)
        messages.success(request, "Thank you. We have your answers.")
        return redirect("portal:home")
