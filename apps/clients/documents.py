"""Rules for uploaded documents: allowed types, size, and a check of the first bytes."""

from django.core.exceptions import ValidationError

MAX_BYTES = 25 * 1024 * 1024

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "heic": "image/heic",
    "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "eml": "message/rfc822",
    "msg": "application/vnd.ms-outlook",
}
ALLOWED_EXTENSIONS = frozenset(CONTENT_TYPES)

# The first bytes a genuine file of this type starts with.
SIGNATURES = {
    "pdf": b"%PDF-",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}


def extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def check_document_upload(upload) -> str:
    """Return the content type for an allowed upload, or raise ValidationError."""
    extension = extension_of(upload.name)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"“{upload.name}” is not an allowed file type. Allowed: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
            + "."
        )
    if upload.size > MAX_BYTES:
        raise ValidationError(f"“{upload.name}” is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    if upload.size == 0:
        raise ValidationError(f"“{upload.name}” is empty.")
    head = upload.read(16)
    upload.seek(0)
    if extension in SIGNATURES and not head.startswith(SIGNATURES[extension]):
        raise ValidationError(f"“{upload.name}” does not look like a real .{extension} file.")
    if extension == "webp" and not (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        raise ValidationError(f"“{upload.name}” does not look like a real .webp file.")
    if extension == "heic" and head[4:8] != b"ftyp":
        raise ValidationError(f"“{upload.name}” does not look like a real .heic file.")
    return CONTENT_TYPES[extension]
