from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.core.storage import MARKER, EncryptedFileSystemStorage


def test_uploaded_files_are_encrypted_on_disk_and_read_back_plain(tmp_path):
    storage = EncryptedFileSystemStorage(location=tmp_path)
    name = storage.save("a/passport.jpg", ContentFile(b"made-up image bytes"))
    raw = (tmp_path / name).read_bytes()
    assert raw.startswith(MARKER)
    assert b"made-up image bytes" not in raw
    assert storage.is_encrypted(name)
    with storage.open(name) as handle:
        assert handle.read() == b"made-up image bytes"


def test_files_saved_before_encryption_are_still_readable(tmp_path):
    (tmp_path / "old.txt").write_bytes(b"plain old file")
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

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "old.pdf").write_bytes(b"plain pdf")
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
