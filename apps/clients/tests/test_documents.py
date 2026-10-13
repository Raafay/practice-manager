import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.clients import documents
from apps.clients.models import Document
from apps.events.models import ActivityEvent

from .factories import ClientFactory, DocumentFactory

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n% made-up test file\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


def upload(client, target, name="letter.pdf", data=PDF, **extra):
    file = SimpleUploadedFile(name, data)
    return client.post(
        reverse("clients:document_upload", args=[target.pk]),
        {"files": file, "category": "correspondence", **extra},
        follow=True,
    )


def test_upload_stores_privately_under_a_random_name(client):
    target = ClientFactory()
    person = staff()
    sign_in(client, person)
    upload(client, target)
    doc = Document.objects.get()
    assert doc.original_name == "letter.pdf" and doc.title == "letter"
    assert doc.file.name.startswith("documents/") and "letter" not in doc.file.name
    assert doc.content_type == "application/pdf" and doc.size == len(PDF)
    assert doc.uploaded_by == person and doc.source == "staff"
    event = ActivityEvent.objects.get(verb="document.uploaded")
    assert event.client == target and "letter" in event.summary


def test_several_files_can_be_uploaded_at_once(client):
    target = ClientFactory()
    sign_in(client, staff())
    response = client.post(
        reverse("clients:document_upload", args=[target.pk]),
        {
            "files": [SimpleUploadedFile("a.pdf", PDF), SimpleUploadedFile("b.txt", b"hello")],
            "category": "other",
        },
    )
    assert response.status_code == 302
    assert Document.objects.count() == 2


@pytest.mark.parametrize(
    ("name", "data", "why"),
    [
        ("program.exe", b"MZ", "allowed file type"),
        ("page.html", b"<script>", "allowed file type"),
        ("image.svg", b"<svg>", "allowed file type"),
        ("fake.pdf", b"this is not a pdf", "real .pdf"),
        ("fake.png", b"%PDF-1.4", "real .png"),
        ("fake.jpg", b"GIF89a", "real .jpg"),
        ("fake.webp", b"RIFFxxxxNOPE", "real .webp"),
        ("empty.txt", b"", "empty"),
    ],
)
def test_wrong_types_and_fake_files_are_refused(client, name, data, why):
    target = ClientFactory()
    sign_in(client, staff())
    response = upload(client, target, name, data)
    assert not Document.objects.exists()
    assert why in " ".join(str(m) for m in response.context["messages"])


def test_size_limit_is_25_megabytes():
    big = SimpleUploadedFile("big.txt", b"x")
    big.size = documents.MAX_BYTES + 1
    with pytest.raises(Exception) as caught:
        documents.check_document_upload(big)
    assert "larger than 25 MB" in str(caught.value)
    ok = SimpleUploadedFile("fine.txt", b"x")
    ok.size = documents.MAX_BYTES
    assert documents.check_document_upload(ok) == "text/plain"


def test_every_allowed_type_has_a_content_type():
    expected = {
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "heic",
        "webp",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "csv",
        "txt",
        "eml",
        "msg",
    }
    assert expected == documents.ALLOWED_EXTENSIONS


def test_identity_and_proof_of_address_are_sensitive_by_default(client):
    target = ClientFactory()
    sign_in(client, staff())
    upload(client, target)
    client.post(
        reverse("clients:document_upload", args=[target.pk]),
        {"files": SimpleUploadedFile("passport.png", PNG), "category": "identity"},
    )
    client.post(
        reverse("clients:document_upload", args=[target.pk]),
        {"files": SimpleUploadedFile("bill.pdf", PDF), "category": "proof_of_address"},
    )
    flags = dict(Document.objects.values_list("original_name", "sensitive"))
    assert flags == {"letter.pdf": False, "passport.png": True, "bill.pdf": True}


def test_document_addresses_redirect_when_signed_out(client):
    doc = DocumentFactory()
    for name in ("clients:document_download", "clients:document_preview"):
        response = client.get(reverse(name, args=[doc.public_id]))
        assert response.status_code == 302 and "/login/" in response["Location"]


def test_files_have_no_public_address(client):
    doc = DocumentFactory()
    assert client.get(f"/media/{doc.file.name}").status_code == 404
    assert client.get(f"/{doc.file.name}").status_code == 404


def test_download_sets_safe_headers_and_is_looked_up_by_public_id(client):
    doc = DocumentFactory(original_name="my letter.txt", content_type="text/plain")
    sign_in(client, staff())
    response = client.get(reverse("clients:document_download", args=[doc.public_id]))
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"".join(response.streaming_content) == b"made up text"
    assert client.get(f"/documents/{doc.pk}/download/").status_code == 404
    # Plain documents are not logged; the file is not sensitive.
    assert not ActivityEvent.objects.filter(verb__startswith="document.downloaded").exists()


def test_preview_is_inline_for_pdfs_and_images_only(client):
    pdf = DocumentFactory(content_type="application/pdf", original_name="a.pdf")
    text = DocumentFactory(content_type="text/plain")
    sign_in(client, staff())
    response = client.get(reverse("clients:document_preview", args=[pdf.public_id]))
    assert response.status_code == 200
    assert not response["Content-Disposition"].startswith("attachment")
    assert response["Content-Type"] == "application/pdf"
    assert client.get(reverse("clients:document_preview", args=[text.public_id])).status_code == 404


def test_sensitive_download_and_view_are_logged(client):
    target = ClientFactory()
    doc = DocumentFactory(
        client=target,
        sensitive=True,
        category="identity",
        content_type="application/pdf",
        original_name="id.pdf",
    )
    person = staff()
    sign_in(client, person)
    client.get(reverse("clients:document_preview", args=[doc.public_id]))
    client.get(reverse("clients:document_download", args=[doc.public_id]))
    verbs = list(ActivityEvent.objects.filter(client=target).values_list("verb", flat=True))
    assert "document.viewed" in verbs and "document.downloaded" in verbs
    assert ActivityEvent.objects.get(verb="document.downloaded").actor == person


def test_sensitive_documents_need_the_right(client):
    doc = DocumentFactory(sensitive=True)
    person = staff()
    role = Role.objects.get(slug=Role.STAFF)
    role.rights = [r for r in role.rights if r != "documents.sensitive"]
    role.save()
    sign_in(client, person)
    assert client.get(reverse("clients:document_download", args=[doc.public_id])).status_code == 403
    assert client.get(reverse("clients:document_edit", args=[doc.public_id])).status_code == 403
    assert client.post(reverse("clients:document_delete", args=[doc.public_id])).status_code == 403
    page = client.get(reverse("clients:documents", args=[doc.client.pk])).content.decode()
    assert "Sensitive, restricted" in page
    assert reverse("clients:document_download", args=[doc.public_id]) not in page
    assert not ActivityEvent.objects.filter(verb="document.downloaded").exists()
    assert owner() and manager()


def test_edit_renames_recategorises_and_marks_sensitive(client):
    doc = DocumentFactory(title="Old title", category="other")
    sign_in(client, staff())
    client.post(
        reverse("clients:document_edit", args=[doc.public_id]),
        {"title": "New title", "category": "tax", "sensitive": "on"},
    )
    doc.refresh_from_db()
    assert (doc.title, doc.category, doc.sensitive) == ("New title", "tax", True)
    event = ActivityEvent.objects.get(verb="document.changed")
    assert event.data["fields"]["title"] == {"old": "Old title", "new": "New title"}
    # Moving into Identity forces it sensitive even when the box is clear.
    client.post(
        reverse("clients:document_edit", args=[doc.public_id]),
        {"title": "ID", "category": "identity"},
    )
    doc.refresh_from_db()
    assert doc.sensitive


def test_soft_delete_hides_the_document_everywhere(client):
    doc = DocumentFactory(title="Hide me")
    sign_in(client, manager())
    client.post(reverse("clients:document_delete", args=[doc.public_id]))
    doc.refresh_from_db()
    assert doc.deleted_at is not None
    listing = client.get(reverse("clients:documents", args=[doc.client.pk]))
    assert listing.context["doc_groups"] == [] and listing.context["hidden_documents"] == []
    assert client.get(reverse("clients:document_download", args=[doc.public_id])).status_code == 404
    assert Document.objects.live().count() == 0 and Document.objects.count() == 1
    assert ActivityEvent.objects.filter(verb="document.deleted").exists()


def test_only_the_owner_can_remove_for_good_and_only_after_deleting(client):
    doc = DocumentFactory()
    stored = doc.file.name
    storage = doc.file.storage
    sign_in(client, owner())
    client.post(reverse("clients:document_purge", args=[doc.public_id]))
    assert Document.objects.filter(pk=doc.pk).exists()  # still live: refused
    client.post(reverse("clients:document_delete", args=[doc.public_id]))
    page = client.get(reverse("clients:documents", args=[doc.client.pk])).content
    assert b"Remove for good" in page
    client.post(reverse("clients:document_purge", args=[doc.public_id]))
    assert not Document.objects.filter(pk=doc.pk).exists()
    assert not storage.exists(stored)
    assert ActivityEvent.objects.filter(verb="document.purged").exists()


def test_a_manager_does_not_see_deleted_documents(client):
    doc = DocumentFactory(title="Gone")
    doc.soft_delete(None)
    sign_in(client, manager())
    assert (
        b"Remove for good"
        not in client.get(reverse("clients:documents", args=[doc.client.pk])).content
    )


def test_document_search_and_grouping(client):
    target = ClientFactory()
    DocumentFactory(client=target, title="VAT return Q1", category="vat")
    DocumentFactory(client=target, title="Engagement letter", category="engagement")
    sign_in(client, staff())
    page = client.get(reverse("clients:documents", args=[target.pk])).content.decode()
    assert "VAT return Q1" in page and "Engagement letter" in page
    found = client.get(
        reverse("clients:documents", args=[target.pk]), {"q": "vat"}
    ).content.decode()
    assert "VAT return Q1" in found and "Engagement letter" not in found
