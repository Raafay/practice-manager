"""Checks for uploaded files: the extension and the first bytes must agree."""

from django.core.exceptions import ValidationError

IMAGE_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    "jpg": (b"\xff\xd8\xff", "image/jpeg"),
    "jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}


def check_image_upload(upload, *, max_bytes: int) -> str:
    """Return the content type of a PNG, JPEG or WebP upload, or raise ValidationError."""
    if upload.size > max_bytes:
        raise ValidationError(
            f"The file is too large. The limit is {max_bytes // (1024 * 1024)} MB."
        )
    extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    head = upload.read(16)
    upload.seek(0)
    if extension == "webp":
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
    elif extension in IMAGE_SIGNATURES:
        signature, content_type = IMAGE_SIGNATURES[extension]
        if head.startswith(signature):
            return content_type
    raise ValidationError("Upload a PNG, JPEG or WebP image.")
