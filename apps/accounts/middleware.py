import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from apps import events
from apps.core.models import PracticeSettings

from .signals import SESSION_SEEN, SESSION_STARTED

SEEN_WRITE_INTERVAL = 60  # seconds; avoids a session write on every request


def _redirect(request, url: str):
    if getattr(request, "htmx", False):
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect(url)


class SessionLimitsMiddleware:
    """End a session after the idle limit, and after the absolute limit in any case."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if user.is_portal:
                idle = settings.PORTAL_SESSION_IDLE_MINUTES * 60
                maximum = settings.PORTAL_SESSION_MAX_HOURS * 3600
            else:
                practice = PracticeSettings.load()
                idle = practice.session_idle_minutes * 60
                maximum = practice.session_max_hours * 3600
            now = time.time()
            session = request.session
            started = session.get(SESSION_STARTED)
            seen = session.get(SESSION_SEEN)
            if started is None:
                session[SESSION_STARTED] = started = now
            expired = (now - started > maximum) or (seen is not None and now - seen > idle)
            if expired:
                events.record(
                    user,
                    "auth.session_expired",
                    f"{user}'s session ended after its time limit.",
                    target=user,
                )
                logout(request)
                messages.info(
                    request, "You were signed out because your session reached its time limit."
                )
                if user.is_portal:
                    return _redirect(request, reverse("portal:login"))
                if getattr(request, "htmx", False):
                    return _redirect(request, reverse("account_login"))
                return redirect_to_login(request.get_full_path())
            if seen is None or now - seen > SEEN_WRITE_INTERVAL:
                session[SESSION_SEEN] = now
        return self.get_response(request)


# Pages a staff member without two-factor may still open: setting it up, and signing out.
MFA_SETUP_URL_NAMES = {
    "mfa_activate_totp",
    "mfa_index",
    "mfa_reauthenticate",
    "mfa_view_recovery_codes",
    "mfa_generate_recovery_codes",
    "mfa_download_recovery_codes",
    "account_logout",
    "account_reauthenticate",
}


class RequireTwoFactorMiddleware:
    """Staff without an authenticator app are sent to set one up, and can reach nothing else."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_staff_kind:
            return None
        match = request.resolver_match
        if match is not None and match.url_name in MFA_SETUP_URL_NAMES:
            return None
        if user.mfa_done:
            return None
        return _redirect(request, reverse("mfa_activate_totp"))


class PortalBoundaryMiddleware:
    """Portal users never reach allauth's pages (passwords, two-factor, staff sign-in).

    They have their own sign-in at /portal/login/ and no password. Signing out is
    the one allauth page they may use.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_portal:
            return None
        module = getattr(view_func, "__module__", "") or ""
        if module.startswith("allauth.") and request.resolver_match.url_name != "account_logout":
            raise PermissionDenied
        return None
