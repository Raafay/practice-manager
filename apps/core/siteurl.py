"""Full addresses for links in emails, letters and jobs.

Each practice has its own address (its primary Domain), so a link always points at
the practice it was made for: the one whose schema the connection is in, whether
inside a web request or a background job (the worker runs each job inside its
practice). There is no single site address any more.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django_tenants.utils import get_public_schema_name


def practice_domain(schema_name: str | None = None) -> str:
    """The primary address of the practice the connection is in (or the one named)."""
    from apps.tenancy.models import Domain

    schema_name = schema_name or connection.schema_name
    if schema_name == get_public_schema_name():
        raise ImproperlyConfigured("No practice is selected, so there is no address to link to.")
    domain = (
        Domain.objects.filter(tenant__schema_name=schema_name)
        .order_by("-is_primary", "domain")
        .values_list("domain", flat=True)
        .first()
    )
    if not domain:
        raise ImproperlyConfigured(f"The practice {schema_name!r} has no web address.")
    return domain


def base_url(schema_name: str | None = None) -> str:
    """For example https://fpas.example.com (a port only in development)."""
    port = f":{settings.SITE_PORT}" if settings.SITE_PORT else ""
    return f"{settings.SITE_SCHEME}://{practice_domain(schema_name)}{port}"


def absolute(path: str) -> str:
    """A full address for a path on the current practice's site, for links in emails."""
    return f"{base_url()}{path}"
