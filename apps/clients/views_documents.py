from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View

from apps.core.permissions import StaffRequiredMixin

from . import services
from .forms import DocumentEditForm, DocumentUploadForm
from .models import Document
from .views_base import done, get_client, render_form


def documents_context(request, client) -> dict:
    query = request.GET.get("q", "").strip()
    documents = client.documents.live().select_related("contact", "uploaded_by")
    if query:
        documents = documents.filter(title__icontains=query)
    groups = []
    for value, label in Document.Category.choices:
        items = [d for d in documents if d.category == value]
        if items:
            groups.append((label, items))
    hidden = []
    if request.user.can("retention.manage"):
        hidden = list(client.documents.filter(deleted_at__isnull=False).order_by("-deleted_at"))
    return {
        "doc_groups": groups,
        "q": query,
        "upload_form": DocumentUploadForm(client=client),
        "can_see_sensitive": request.user.can("documents.sensitive"),
        "hidden_documents": hidden,
        "doc_count": documents.count(),
    }


class DocumentUploadView(StaffRequiredMixin, View):
    def post(self, request, pk):
        client = get_client(pk)
        form = DocumentUploadForm(request.POST, request.FILES, client=client)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("clients:documents", pk=client.pk)
        data = form.cleaned_data
        stored = 0
        for upload in request.FILES.getlist("files"):
            try:
                services.store_document(
                    request.user,
                    client,
                    upload,
                    category=data["category"],
                    contact=data["contact"],
                    sensitive=data["sensitive"],
                )
                stored += 1
            except ValidationError as error:
                messages.error(request, error.message)
        if stored:
            messages.success(request, f"{stored} file{'s' if stored != 1 else ''} uploaded.")
        return redirect("clients:documents", pk=client.pk)


def _live_document(public_id) -> Document:
    return get_object_or_404(Document.objects.live().select_related("client"), public_id=public_id)


def _serve(request, document: Document, *, download: bool):
    if not services.can_open_document(request.user, document):
        raise PermissionDenied
    if not download and not document.can_preview:
        raise Http404
    services.record_document_access(request.user, document, download=download)
    try:
        handle = document.file.open("rb")
    except FileNotFoundError as error:
        raise Http404 from error
    response = FileResponse(
        handle,
        as_attachment=download,
        filename=document.original_name,
        content_type=document.content_type or "application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


class DocumentDownloadView(StaffRequiredMixin, View):
    def get(self, request, public_id):
        return _serve(request, _live_document(public_id), download=True)


class DocumentPreviewView(StaffRequiredMixin, View):
    def get(self, request, public_id):
        return _serve(request, _live_document(public_id), download=False)


class DocumentEditView(StaffRequiredMixin, View):
    def _render(self, request, document, form, status=200):
        return render_form(
            request,
            title=f"Edit {document.title}",
            form=form,
            action=reverse("clients:document_edit", args=[document.public_id]),
            target="drawer",
            status=status,
        )

    def get(self, request, public_id):
        document = _live_document(public_id)
        if not services.can_open_document(request.user, document):
            raise PermissionDenied
        return self._render(request, document, DocumentEditForm(instance=document))

    def post(self, request, public_id):
        document = _live_document(public_id)
        if not services.can_open_document(request.user, document):
            raise PermissionDenied
        form = DocumentEditForm(request.POST, instance=document)
        if not form.is_valid():
            return self._render(request, document, form, 422)
        services.update_document(request.user, document, form)
        return done(request, reverse("clients:documents", args=[document.client_id]), "Saved.")


class DocumentDeleteView(StaffRequiredMixin, View):
    def post(self, request, public_id):
        document = _live_document(public_id)
        if not services.can_open_document(request.user, document):
            raise PermissionDenied
        services.delete_document(request.user, document)
        return done(
            request,
            reverse("clients:documents", args=[document.client_id]),
            f"{document.title} was deleted.",
        )


class DocumentPurgeView(StaffRequiredMixin, View):
    def has_access(self, request) -> bool:
        return request.user.can("retention.manage")

    def post(self, request, public_id):
        document = get_object_or_404(Document, public_id=public_id)
        client_id = document.client_id
        try:
            services.purge_document(request.user, document)
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "The document was removed for good.")
        return done(request, reverse("clients:documents", args=[client_id]))
