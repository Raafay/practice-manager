"""File storage that encrypts every uploaded file before it is written.

Files are encrypted with the same keys as the encrypted fields
(settings.FIELD_ENCRYPTION_KEYS, newest first), so a copy of the bucket or the
disk is unreadable without them. Files written before encryption was switched on
have no marker and are read as they are.
"""

import io

from django.core.files.base import ContentFile, File
from django.core.files.storage import FileSystemStorage

from .fields import get_fernet

MARKER = b"PMENC1\n"


def seal_bytes(data: bytes) -> bytes:
    return MARKER + get_fernet().encrypt(data)


def open_bytes(data: bytes) -> bytes:
    if data.startswith(MARKER):
        return get_fernet().decrypt(data[len(MARKER) :])
    return data


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
    pass


try:  # Production only; django-storages[s3] is installed there.
    from storages.backends.s3 import S3Storage
except ImportError:  # pragma: no cover
    S3Storage = None
else:

    class EncryptedS3Storage(EncryptedStorageMixin, S3Storage):
        pass
