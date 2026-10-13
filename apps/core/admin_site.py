from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


class ControlAdminSite(admin.AdminSite):
    """A last resort for the owner. Signing in goes through the normal two-factor page."""

    site_header = "Practice Manager control"
    site_title = "Control"
    index_title = "Records"

    def has_permission(self, request):
        user = request.user
        return bool(
            user.is_authenticated and user.is_staff_kind and user.is_owner and user.mfa_done
        )

    def login(self, request, extra_context=None):
        # Django's own admin sign-in checks the password only, so it is never used.
        target = request.GET.get("next") or reverse("admin:index")
        if request.user.is_authenticated:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        return redirect(f"{reverse('account_login')}?{urlencode({'next': target})}")
