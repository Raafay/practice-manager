from django.db import connection
from django.http import HttpResponseNotFound
from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name


def not_found():
    """A plain 404 that reads nothing from any practice. It is answered before the
    security-header middleware runs, so it sets the headers that matter itself."""
    response = HttpResponseNotFound("Not found.", content_type="text/plain; charset=utf-8")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


class PracticeMiddleware(TenantMainMiddleware):
    """Choose the practice, and so the database schema, from the web address.

    An address that is not a practice's gets a plain 404 and the connection stays
    on the public schema, which holds no practice data. The public schema has no
    pages of its own yet (the platform pages come in later stages).
    """

    def no_tenant_found(self, request, hostname):
        return not_found()

    def process_request(self, request):
        response = super().process_request(request)
        if response is not None:
            return response
        if request.tenant.schema_name == get_public_schema_name():
            connection.set_schema_to_public()
            return not_found()
        return None
