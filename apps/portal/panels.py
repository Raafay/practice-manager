"""Overview panel: new requests."""

from .models import Request

LIMIT = 6


def overview_context(user) -> dict:
    new = Request.objects.new().select_related("client").order_by("-urgency", "-received_at")
    return {"request_rows": list(new[:LIMIT]), "request_total": new.count()}
