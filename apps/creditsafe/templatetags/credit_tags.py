from django import template

from .. import services

register = template.Library()


@register.inclusion_tag("creditsafe/_badge.html")
def credit_badge(client):
    return {"check": services.latest(client) if client.company_number else None}
