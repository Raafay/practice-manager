"""The only way to write an activity event, and the notify function."""

import json

from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder

from apps.core.fields import EncryptedTextField

from .context import get_current
from .middleware import request_ip
from .models import ActivityEvent, Notification

ENCRYPTED_PLACEHOLDER = "(encrypted value changed)"


def _signed_in(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def record(
    actor,
    verb: str,
    summary: str,
    client=None,
    target=None,
    *,
    actor_label: str = "",
    request=None,
    **data,
) -> ActivityEvent:
    """Write one activity event.

    actor: the user who acted. None means the signed-in user of the current
    request, or the system when there is none. `data` must never hold the value
    of an encrypted field: build it with `changes()` or `snapshot()`.
    """
    if client is not None:
        raise ValueError("The client link on events is added in Stage 2.")

    info = get_current()
    if request is not None:
        ip_address = request_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
        current_user = getattr(request, "user", None)
    else:
        ip_address = info.ip_address if info else None
        user_agent = info.user_agent if info else ""
        current_user = info.user if info else None

    if actor is None and _signed_in(current_user):
        actor = current_user
    actor_obj = actor if _signed_in(actor) else None
    if not actor_label:
        actor_label = str(actor_obj) if actor_obj else "System"

    event = ActivityEvent(
        actor=actor_obj,
        actor_label=actor_label[:200],
        verb=verb,
        summary=summary[:500],
        data=json.loads(json.dumps(data, cls=DjangoJSONEncoder)),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if target is not None:
        event.target_type = ContentType.objects.get_for_model(target)
        event.target_id = str(target.pk)
        event.target_label = str(target)[:200]
    event.save()
    return event


def snapshot(instance, fields: list[str]) -> dict:
    """Current values of some fields, safe for event data. Encrypted fields are hidden."""
    values = {}
    for name in fields:
        field = instance._meta.get_field(name)
        if isinstance(field, EncryptedTextField):
            values[name] = "(encrypted)"
        elif field.many_to_many:
            values[name] = (
                sorted(str(obj) for obj in getattr(instance, name).all()) if instance.pk else []
            )
        elif field.is_relation:
            related = getattr(instance, name)
            values[name] = str(related) if related is not None else None
        else:
            values[name] = getattr(instance, name)
    return values


def changes(before: dict, after: dict) -> dict:
    """Fields whose value differs, as {field: {"old": ..., "new": ...}}."""
    diff = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            if old == "(encrypted)" or new == "(encrypted)":
                diff[key] = ENCRYPTED_PLACEHOLDER
            else:
                diff[key] = {"old": old, "new": new}
    return diff


def notify(user, message: str, link: str = "") -> Notification:
    """Put a message under one user's bell. Links must be paths on this site."""
    if link and (not link.startswith("/") or link.startswith(("//", "/\\"))):
        raise ValueError("A notification link must be a path on this site, starting with /.")
    return Notification.objects.create(user=user, message=message[:300], link=link)
