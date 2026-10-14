import base64

from django import template
from django.core.cache import cache

register = template.Library()


@register.simple_tag
def logo_src(practice):
    """The practice logo as a data address, so the file itself never needs a public address."""
    if not practice or not practice.logo:
        return ""
    key = f"logo-data:{practice.pk}:{practice.updated_at:%Y%m%d%H%M%S%f}"
    value = cache.get(key)
    if value is None:
        try:
            with practice.logo.open("rb") as handle:
                data = handle.read()
        except (OSError, ValueError):
            return ""
        if len(data) > 1_000_000:
            return ""
        value = (
            f"data:{practice.logo_content_type or 'image/png'};base64,"
            + base64.b64encode(data).decode()
        )
        cache.set(key, value, 3600)
    return value


@register.filter
def get_item(mapping, key):
    """mapping|get_item:key for dictionaries with variable keys (form answers, errors)."""
    if isinstance(mapping, dict):
        return mapping.get(key, "")
    return ""


@register.inclusion_tag("portal/_state_badge.html")
def portal_state_badge(client):
    """The client's portal state for the client header: not invited, invited or active."""
    from apps.portal import services

    label, tone = services.PORTAL_STATE_LABELS[services.portal_state(client)]
    return {"label": label, "tone": tone}
