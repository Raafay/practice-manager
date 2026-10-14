"""Portal pages for a signed-in client contact (spec 08 section 2)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Document
from apps.core import ratelimit
from apps.services.models import Deadline

from . import requests as request_services
from . import services
from .access import SESSION_CLIENT, PortalRequiredMixin, no_index
from .forms import PortalRequestForm, UploadForm
from .models import PortalItem, Request


class PortalView(PortalRequiredMixin, View):
    """Base for every portal page: signed in as a portal user, never cached."""

    template = ""

    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def page(self, request, context=None, *, status=200, template=None):
        base = {
            "portal_client": request.portal_client,
            "portal_clients": request.portal_clients,
            "portal_contact": request.portal_contact,
        }
        base.update(context or {})
        return no_index(render(request, template or self.template, base, status=status))

    # Everything a view loads comes from here, so another client's data cannot be reached.
    def items(self, request):
        return PortalItem.objects.for_portal_user(request.user).filter(client=request.portal_client)

    def documents(self, request):
        return Document.objects.for_portal_user(request.user).filter(client=request.portal_client)


class SwitchView(PortalView):
    def post(self, request):
        wanted = request.POST.get("client", "")
        match = next((c for c in request.portal_clients if str(c.public_id) == wanted), None)
        if match is None:
            raise Http404
        request.session[SESSION_CLIENT] = str(match.public_id)
        return redirect("portal:home")


class HomeView(PortalView):
    template = "portal/home.html"

    def get(self, request):
        client = request.portal_client
        today = timezone.localdate()
        deadlines = (
            Deadline.objects.for_portal_user(request.user)
            .filter(client=client, due_date__gte=today - timedelta(days=0))
            .order_by("due_date")
            .values("label", "due_date")[:6]
        )
        return self.page(
            request,
            {
                "things_to_do": self.items(request).open(),
                "recent_documents": self.documents(request)
                .filter(shared_with_portal=True)
                .order_by("-created_at")[:5],
                "deadlines": list(deadlines),
            },
        )


class DocumentsView(PortalView):
    template = "portal/documents.html"

    def get(self, request, form=None, status=200):
        documents = self.documents(request).order_by("-created_at")
        return self.page(
            request,
            {
                "shared": [d for d in documents if d.source != "portal"],
                "uploaded": [d for d in documents if d.source == "portal"],
                "form": form or UploadForm(),
            },
            status=status,
        )


class UploadView(PortalView):
    """Choose a category, add a note, pick files. Each file becomes a Document (source portal)."""

    def post(self, request):
        form = UploadForm(request.POST)
        uploads = request.FILES.getlist("files")
        if not form.is_valid():
            return self._again(request, form)
        try:
            documents = services.upload_many(
                request.user,
                request.portal_client,
                uploads,
                category=form.cleaned_data["category"],
                note=form.cleaned_data["note"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._again(request, form)
        from django.contrib import messages

        messages.success(
            request,
            f"Thank you. We received {len(documents)} file{'s' if len(documents) != 1 else ''}.",
        )
        return redirect("portal:documents")

    def _again(self, request, form):
        documents = self.documents(request).order_by("-created_at")
        return self.page(
            request,
            {
                "shared": [d for d in documents if d.source != "portal"],
                "uploaded": [d for d in documents if d.source == "portal"],
                "form": form,
            },
            status=422,
            template="portal/documents.html",
        )


class DocumentDownloadView(PortalView):
    def get(self, request, public_id):
        document = get_object_or_404(
            Document.objects.for_portal_user(request.user), public_id=public_id
        )
        client_services.record_document_access(request.user, document, download=True)
        if not document.sensitive:
            events.record(
                request.user,
                "document.downloaded_portal",
                f"{request.portal_contact or request.user} downloaded {document.title} "
                "in the portal.",
                client=document.client,
                target=document,
            )
        response = FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.original_name,
            content_type=document.content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return no_index(response)


class RequestsView(PortalView):
    template = "portal/requests.html"

    def get(self, request):
        queryset = (
            Request.objects.for_portal_user(request.user)
            .filter(client=request.portal_client)
            .order_by("-received_at")
        )
        return self.page(request, {"requests": queryset})


class RequestNewView(PortalView):
    template = "portal/request_new.html"

    def get(self, request):
        initial = {}
        if request.GET.get("change"):
            initial = {"subject": "A change to our details"}
        return self.page(request, {"form": PortalRequestForm(initial=initial)})

    def post(self, request):
        form = PortalRequestForm(request.POST)
        if not form.is_valid():
            return self.page(request, {"form": form}, status=422)
        try:
            obj = request_services.create_request(
                channel=Request.Channel.PORTAL,
                client=request.portal_client,
                contact=request.portal_contact,
                sender_name=request.portal_contact.full_name
                if request.portal_contact
                else request.user.name,
                sender_email=request.user.email,
                subject=form.cleaned_data["subject"],
                body=form.cleaned_data["body"],
                urgency=form.cleaned_data["urgency"],
                uploads=request.FILES.getlist("files"),
                logged_by=None,
                ip=ratelimit.client_ip(request),
                actor_label=str(request.portal_contact or request.user),
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.page(request, {"form": form}, status=422)
        return redirect("portal:request_detail", public_id=obj.public_id)


class RequestDetailView(PortalView):
    template = "portal/request_detail.html"

    def get(self, request, public_id):
        obj = get_object_or_404(
            Request.objects.for_portal_user(request.user).filter(client=request.portal_client),
            public_id=public_id,
        )
        return self.page(request, {"req": obj})


class DetailsView(PortalView):
    """What the practice holds, read-only. Changes go through a request."""

    template = "portal/details.html"

    def get(self, request):
        client = request.portal_client
        people = [
            {
                "name": link.contact.display_name,
                "roles": link.role_labels,
                "is_you": link.contact_id == getattr(request.portal_contact, "pk", None),
            }
            for link in client.client_contacts.filter(resigned_on__isnull=True).select_related(
                "contact"
            )
        ]
        return self.page(request, {"people": people})
