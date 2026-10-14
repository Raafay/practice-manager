from allauth.mfa.base import views as mfa_views
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.tasks.views import OverviewView

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
    path("", include("apps.clients.urls")),
    path("", include("apps.jobs.urls")),
    path("", include("apps.companieshouse.urls")),
    path("", include("apps.services.urls")),
    path("", include("apps.tasks.urls")),
    path("", include("apps.comms.urls")),
    path("", include("apps.onboarding.urls")),
    path("", include("apps.aml.urls")),
    path("", include("apps.pipeline.urls")),
    path("", include("apps.portal.urls")),
    path("", include("apps.timekeeping.urls")),
    path("", include("apps.finance.urls")),
    path("", include("apps.imports.urls")),
    path("", include("apps.reports.urls")),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
