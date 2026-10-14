from django import template

from apps.aml import services

register = template.Library()


@register.inclusion_tag("aml/_badge.html")
def aml_badge(client):
    key, label, tone = services.state_of(client)
    level = services.level_of(client)
    return {"label": label, "tone": tone, "level": level, "client": client}
