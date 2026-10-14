"""Access for portal pages: signed in, kind portal, active, and linked to at least one client."""

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from apps.clients.models import Client

SESSION_CLIENT = "portal_client"


def selected_client(request, clients):
    """The client the person is looking at: their choice if it is still theirs, else the first."""
    wanted = request.session.get(SESSION_CLIENT)
    chosen = None
    if wanted:
        chosen = next((c for c in clients if str(c.public_id) == wanted), None)
    return chosen or (clients[0] if clients else None)


class PortalRequiredMixin:
    """Every portal view uses this. Queries then go through `for_portal_user` managers."""

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("portal:login"))
        if not (user.is_active and user.is_portal):
            raise PermissionDenied  # a staff account cannot use the portal
        clients = list(Client.objects.for_portal_user(user).order_by("name"))
        if not clients:
            raise Http404
        request.portal_clients = clients
        request.portal_client = selected_client(request, clients)
        request.portal_contact = getattr(user, "portal_contact", None)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(portal_context(self.request))
        return context


def portal_context(request) -> dict:
    return {
        "portal_client": request.portal_client,
        "portal_clients": request.portal_clients,
        "portal_contact": request.portal_contact,
    }


def no_index(response):
    response["Cache-Control"] = "no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    return response


def to_login():
    return redirect("portal:login")
