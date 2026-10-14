"""Action links: one person, one purpose, one object, one use. See spec 01 section 5.

Only the SHA-256 hash of the token is stored, so a copy of the database cannot be
turned into working links. A public page looks a token up with `resolve()`.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.utils import timezone

from .models import ActionLink

DEFAULT_DAYS = 14


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def create(
    *, purpose, contact, client, object_id, created_by=None, days=DEFAULT_DAYS, expires_at=None
):
    """Make a link. Returns (link, token); the token is shown once and is not stored."""
    token = secrets.token_urlsafe(32)
    link = ActionLink.objects.create(
        token_hash=hash_token(token),
        purpose=purpose,
        contact=contact,
        client=client,
        object_id=object_id,
        expires_at=expires_at or timezone.now() + timedelta(days=days),
        created_by=created_by,
    )
    return link, token


def resolve(token: str, purpose: str) -> ActionLink | None:
    """The live link for a token, or None. Expired, cancelled and wrong-purpose links give None."""
    if not token or len(token) > 100:
        return None
    digest = hash_token(token)
    link = ActionLink.objects.filter(token_hash=digest).select_related("contact", "client").first()
    if link is None or not hmac.compare_digest(link.token_hash, digest):
        return None
    if link.purpose != purpose or link.cancelled_at or link.expires_at <= timezone.now():
        return None
    return link


def cancel_for(purpose: str, object_id: int) -> int:
    return ActionLink.objects.filter(
        purpose=purpose, object_id=object_id, cancelled_at__isnull=True, used_at__isnull=True
    ).update(cancelled_at=timezone.now())
