"""Access checks for views. Deny by default: every staff view uses one of these."""

from functools import wraps

from allauth.account.decorators import reauthentication_required
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.shortcuts import redirect


def check_staff(request) -> None | object:
    """Return a redirect response, raise PermissionDenied, or return None if allowed.

    Allowed means: signed in, a staff account, active, and two-factor done.
    """
    user = request.user
    if not user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not (user.is_active and user.is_staff_kind):
        raise PermissionDenied
    if not user.mfa_done:
        return redirect("mfa_activate_totp")
    return None


class StaffRequiredMixin(AccessMixin):
    """Signed in, kind staff, active, two-factor done.

    require_reauth: a POST needs the password entered in the last few minutes.
    """

    require_reauth = False
    # Opening the page does not need the password; only the change does. A view that
    # acts on GET (a file download) sets this to False so the GET is guarded too.
    reauth_allow_get = True

    def dispatch(self, request, *args, **kwargs):
        response = check_staff(request)
        if response is not None:
            return response
        if not self.has_access(request):
            raise PermissionDenied
        if self.require_reauth:
            # Before a change (not a page view), allauth asks for the password
            # again if it was not entered recently, then replays the request.
            guarded = reauthentication_required(super().dispatch, allow_get=self.reauth_allow_get)
            return guarded(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def has_access(self, request) -> bool:
        return True


class CapabilityRequiredMixin(StaffRequiredMixin):
    """Staff with every right in `required_rights`."""

    required_rights: tuple[str, ...] = ()

    def has_access(self, request) -> bool:
        if not self.required_rights:
            raise ImproperlyConfigured(f"{type(self).__name__} lists no required_rights.")
        return all(request.user.can(right) for right in self.required_rights)


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = check_staff(request)
        if response is not None:
            return response
        return view(request, *args, **kwargs)

    return wrapper


def right_required(*rights: str):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            response = check_staff(request)
            if response is not None:
                return response
            if not all(request.user.can(right) for right in rights):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
