from allauth.mfa.base import views as mfa_views
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views import OverviewView

urlpatterns = [
    path("", OverviewView.as_view(), name="overview"),
    path("control/", admin.site.urls),
    # Email addresses are managed by the owner, not through allauth's own page.
    path("email/", RedirectView.as_view(pattern_name="accounts:profile"), name="account_email"),
    # allauth registers this page only if "trust this browser" is on when URLs load.
    # The owner can switch it on and off while the site runs, so it always exists.
    path("2fa/trust/", mfa_views.trust, name="mfa_trust"),
    path("", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.events.urls")),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
