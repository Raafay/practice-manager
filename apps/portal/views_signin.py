from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from . import signin
from .access import no_index
from .forms import CodeForm, EmailForm

GENERIC_ERROR = (
    "That code is not right, or it has expired. Check it, or start again for a new code."
)


def _page(request, stage, form, *, error="", status=200):
    return no_index(
        render(
            request,
            "portal/login.html",
            {"stage": stage, "form": form, "error": error},
            status=status,
        )
    )


@method_decorator(never_cache, name="dispatch")
class PortalLoginView(View):
    def get(self, request):
        if request.user.is_authenticated and request.user.is_portal:
            return redirect("portal:home")
        request.session.pop(signin.SESSION_EMAIL, None)
        wanted = request.GET.get("next", "")
        if wanted.startswith("/portal/") and not wanted.startswith("//"):
            request.session["portal_next"] = wanted
        return _page(request, "email", EmailForm())

    def post(self, request):
        if request.user.is_authenticated and not request.user.is_portal:
            raise PermissionDenied  # a staff account cannot use the portal sign-in
        form = EmailForm(request.POST)
        if not form.is_valid():
            return _page(request, "email", form, status=422)
        email = form.cleaned_data["email"].strip().lower()
        signin.send_code(request, email)
        request.session[signin.SESSION_EMAIL] = email
        return _page(request, "code", CodeForm())


@method_decorator(never_cache, name="dispatch")
class PortalCodeView(View):
    def get(self, request):
        return redirect("portal:login")

    def post(self, request):
        email = request.session.get(signin.SESSION_EMAIL, "")
        if not email:
            return redirect("portal:login")
        form = CodeForm(request.POST)
        if not form.is_valid():
            return _page(request, "code", form, status=422)
        user = signin.check_code(request, email, form.cleaned_data["code"])
        if user is None:
            return _page(request, "code", CodeForm(), error=GENERIC_ERROR, status=422)
        request.session.pop(signin.SESSION_EMAIL, None)
        target = request.session.pop("portal_next", "")
        if target.startswith("/portal/") and not target.startswith("//"):
            return redirect(target)
        return redirect("portal:home")


@require_POST
def portal_logout(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "You have been signed out.")
    return redirect("portal:login")
