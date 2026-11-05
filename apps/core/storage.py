"""File storage that encrypts every uploaded file before it is written.

Files are encrypted with the same keys as the encrypted fields
(settings.FIELD_ENCRYPTION_KEYS, newest first), so a copy of the bucket or the
disk is unreadable without them. Files written before encryption was switched on
have no marker and are read as they are.

Each practice's files live in its own folder, named after its schema
(`<MEDIA_ROOT or bucket>/<schema>/...`). The folder is chosen from the practice the
connection is in, never from the file's name, so the same name opens a different
file (or none) in another practice, and a name that climbs out of the folder
("../other/...") or is absolute is refused. With no practice selected, no file can
be read or written at all.
"""

import io
import os

from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage
from django.db import connection

from .fields import get_fernet

MARKER = b"PMENC1\n"


def seal_bytes(data: bytes) -> bytes:
    return MARKER + get_fernet().encrypt(data)


def open_bytes(data: bytes) -> bytes:
    if data.startswith(MARKER):
        return get_fernet().decrypt(data[len(MARKER) :])
    return data


def practice_folder() -> str:
    """The current practice's folder name: its schema. Refused outside a practice."""
    from django_tenants.utils import get_public_schema_name

    schema = getattr(connection, "schema_name", "")
    if not schema or schema == get_public_schema_name():
        raise SuspiciousFileOperation("No practice is selected, so no file can be opened.")
    return schema


class EncryptedStorageMixin:
    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        return super()._save(name, ContentFile(seal_bytes(content.read())))

    def _open(self, name, mode="rb"):
        with super()._open(name, "rb") as handle:
            data = open_bytes(handle.read())
        return File(io.BytesIO(data), name=name)

    def is_encrypted(self, name) -> bool:
        with super()._open(name, "rb") as handle:
            return handle.read(len(MARKER)) == MARKER

    def url(self, name):
        raise NotImplementedError("Uploaded files are only served through permission checks.")


class EncryptedFileSystemStorage(EncryptedStorageMixin, FileSystemStorage):
    """Files on disk under MEDIA_ROOT/<schema>/. Django's safe_join refuses any name
    that resolves outside that folder."""

    @property
    def location(self):
        return os.path.abspath(os.path.join(self.base_location, practice_folder()))


try:  # Production only; django-storages[s3] is installed there.
    from storages.backends.s3 import S3Storage
except ImportError:  # pragma: no cover
    S3Storage = None
else:

    class EncryptedS3Storage(EncryptedStorageMixin, S3Storage):
        """Files in the bucket under <schema>/. django-storages' safe_join refuses
        any name that resolves outside that prefix."""

        @property
        def location(self):
            base = (self._base_location or "").strip("/")
            return f"{base}/{practice_folder()}" if base else practice_folder()

        @location.setter
        def location(self, value):
            self._base_location = value

        _base_location = ""
