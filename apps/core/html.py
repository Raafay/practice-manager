"""Rich text from users is cleaned with nh3 before it is stored or shown."""

import nh3

ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "div", "em", "h1", "li", "ol", "p", "pre",
    "strong", "ul",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {"a": {"href"}}
ALLOWED_SCHEMES = {"http", "https", "mailto"}


def clean_html(value: str) -> str:
    """Keep the formatting Trix produces and drop everything else, scripts included."""
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer nofollow",
    )
