from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.views import View

from apps.clients.views_base import done, get_client
from apps.core.permissions import CapabilityRequiredMixin

from . import services


class CheckView(CapabilityRequiredMixin, View):
    """Fetch a credit report now. Each costs money, so it needs clients.status."""

    required_rights = ("clients.status",)

    def post(self, request, pk):
        client = get_client(pk)
        try:
            check = services.check_client(request.user, client)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(
                request,
                f"Credit rating: {check.rating or 'no band'}"
                + (f", score {check.score}" if check.score is not None else "")
                + ".",
            )
        return done(request, reverse("aml:tab", args=[client.pk]))
