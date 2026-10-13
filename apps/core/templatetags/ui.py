"""Template tags and filters loaded on every template (see TEMPLATES builtins)."""

import re
from functools import lru_cache
from pathlib import Path

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.core.fields import mask
from apps.core.money import format_money

register = template.Library()

ICON_DIR = Path(__file__).resolve().parent.parent / "icons"
ICON_NAME = re.compile(r"^[a-z0-9-]+$")
SVG_OPEN = re.compile(r"<svg\b[^>]*>")


@lru_cache(maxsize=256)
def _icon_svg(name: str, variant: str) -> tuple[str, str]:
    if not ICON_NAME.match(name) or variant not in {"outline", "mini"}:
        raise template.TemplateSyntaxError(f"Unknown icon {name!r}")
    path = ICON_DIR / variant / f"{name}.svg"
    if not path.is_file():
        raise template.TemplateSyntaxError(f"Unknown icon {name!r}. Add it to apps/core/icons/.")
    svg = path.read_text()
    opening = SVG_OPEN.search(svg).group(0)
    inner = svg[len(opening) + svg.index(opening) :].rsplit("</svg>", 1)[0].strip()
    attrs = {
        "outline": 'fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"',
        "mini": 'viewBox="0 0 20 20" fill="currentColor"',
    }[variant]
    return attrs, inner


@register.simple_tag
def icon(name: str, css: str = "size-5", variant: str = "outline", label: str = ""):
    """An inline Heroicon (MIT licence). Decorative unless a label is given."""
    attrs, inner = _icon_svg(name, variant)
    if label:
        a11y = format_html('role="img" aria-label="{}"', label)
    else:
        a11y = mark_safe('aria-hidden="true" focusable="false"')  # noqa: S308
    return format_html(
        '<svg xmlns="http://www.w3.org/2000/svg" class="{}" {} {}>{}</svg>',
        css,
        mark_safe(attrs),  # noqa: S308 - fixed strings above
        a11y,
        mark_safe(inner),  # noqa: S308 - bundled Heroicons files
    )


@register.filter
def money(value, pence=True):
    return format_money(value, pence=pence is not False and pence != "no")


@register.filter
def masked(value):
    return mask(value)


@register.filter
def can(user, right: str) -> bool:
    """{% if request.user|can:"fees.view" %}. False for anyone signed out."""
    return bool(getattr(user, "is_authenticated", False) and user.can(right))


@register.simple_tag(takes_context=True)
def page_query(context, number):
    """The current query string with the page number changed (for pagination links)."""
    from apps.core.pagination import page_query as build

    return build(context["request"], number)


@register.filter
def split_list(value: str) -> list[str]:
    """ "a,b,c"|split_list gives ["a", "b", "c"]. For short fixed lists in templates."""
    return [item.strip() for item in value.split(",") if item.strip()]


@register.filter
def split_pairs(value: str) -> list[tuple[str, str]]:
    """ "key:Label,key2:Label two"|split_pairs gives [("key", "Label"), ...]."""
    return [tuple(item.split(":", 1)) for item in split_list(value)]


@register.filter
def styled(bound_field):
    """Render a field's widget with the styleguide class, for forms we do not own (allauth)."""
    widget = bound_field.field.widget
    if widget.attrs.get("class") or getattr(widget, "input_type", "") == "hidden":
        return bound_field
    from apps.core.forms import widget_css

    return bound_field.as_widget(attrs={"class": widget_css(widget)})


@register.filter
def pretty_json(value) -> str:
    import json

    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
