import pytest
from django.core.exceptions import SuspiciousFileOperation, SuspiciousOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.core.storage import MARKER, EncryptedFileSystemStorage


def test_uploaded_files_are_encrypted_on_disk_and_read_back_plain(tmp_path):
    storage = EncryptedFileSystemStorage(location=tmp_path)
    name = storage.save("a/passport.jpg", ContentFile(b"made-up image bytes"))
    raw = (tmp_path / "practice_a" / name).read_bytes()
    assert raw.startswith(MARKER)
    assert b"made-up image bytes" not in raw
    assert storage.is_encrypted(name)
    with storage.open(name) as handle:
        assert handle.read() == b"made-up image bytes"


def test_files_saved_before_encryption_are_still_readable(tmp_path):
    (tmp_path / "practice_a").mkdir()
    (tmp_path / "practice_a" / "old.txt").write_bytes(b"plain old file")
    storage = EncryptedFileSystemStorage(location=tmp_path)
    assert not storage.is_encrypted("old.txt")
    with storage.open("old.txt") as handle:
        assert handle.read() == b"plain old file"


def test_the_default_storage_encrypts():
    assert isinstance(default_storage, EncryptedFileSystemStorage)


def test_encrypt_files_encrypts_old_plain_files(db, settings, tmp_path):
    from django.core.management import call_command

    from apps.clients.models import Document
    from apps.clients.tests.factories import ClientFactory

    settings.MEDIA_ROOT = tmp_path
    from django.core.files.storage import default_storage

    (tmp_path / "practice_a" / "docs").mkdir(parents=True)
    (tmp_path / "practice_a" / "docs" / "old.pdf").write_bytes(b"plain pdf")
    fields = {f.name for f in Document._meta.fields}
    doc = Document.objects.create(
        client=ClientFactory(),
        file="docs/old.pdf",
        original_name="old.pdf",
        **({"title": "Old"} if "title" in fields else {}),
    )
    call_command("encrypt_files", stdout=__import__("io").StringIO())
    assert default_storage.is_encrypted(doc.file.name)
    with default_storage.open(doc.file.name) as handle:
        assert handle.read() == b"plain pdf"
    call_command("encrypt_files", stdout=__import__("io").StringIO())


# ---------------------------------------------------------------------------
# A folder per practice (Stage 14).


def test_each_practice_has_its_own_folder(tmp_path):
    from django_tenants.utils import schema_context

    storage = EncryptedFileSystemStorage(location=tmp_path)
    name = storage.save("docs/id.jpg", ContentFile(b"made-up A bytes"))
    assert (tmp_path / "practice_a" / name).exists()
    with schema_context("practice_b"):
        assert not storage.exists(name)
        with pytest.raises(FileNotFoundError):
            storage.open(name)
        other = storage.save("docs/id.jpg", ContentFile(b"made-up B bytes"))
        assert (tmp_path / "practice_b" / other).exists()
    with storage.open(name) as handle:
        assert handle.read() == b"made-up A bytes"


@pytest.mark.parametrize(
    "name", ["../practice_b/docs/id.jpg", "docs/../../practice_b/docs/id.jpg", "/etc/passwd"]
)
def test_a_name_outside_the_practice_folder_is_refused(tmp_path, name):
    storage = EncryptedFileSystemStorage(location=tmp_path)
    for action in (storage.open, storage.exists, storage.delete, storage.path):
        with pytest.raises(SuspiciousFileOperation):
            action(name)
    with pytest.raises(SuspiciousFileOperation):
        storage.save(name, ContentFile(b"x"))


def test_no_file_is_reached_outside_a_practice(tmp_path):
    from django_tenants.utils import schema_context

    storage = EncryptedFileSystemStorage(location=tmp_path)
    with schema_context("public"), pytest.raises(SuspiciousFileOperation):
        storage.open("docs/id.jpg")


def test_the_bucket_storage_uses_a_prefix_per_practice():
    from django_tenants.utils import schema_context

    from apps.core.storage import EncryptedS3Storage

    storage = EncryptedS3Storage(bucket_name="made-up", location="files")
    assert storage._normalize_name("docs/id.jpg") == "files/practice_a/docs/id.jpg"
    with schema_context("practice_b"):
        assert storage._normalize_name("docs/id.jpg") == "files/practice_b/docs/id.jpg"
    with pytest.raises(SuspiciousOperation):
        storage._normalize_name("../practice_b/docs/id.jpg")
    assert EncryptedS3Storage(bucket_name="made-up")._normalize_name("a") == "practice_a/a"
