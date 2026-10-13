from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.views import OverviewView

urlpatterns = [
    path("", OverviewView.as_view(), name="overview"),
    path("control/", admin.site.urls),
    # Email addresses are managed by the owner, not through allauth's own page.
    path("email/", RedirectView.as_view(pattern_name="accounts:profile"), name="account_email"),
    path("", include("allauth.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.events.urls")),
]

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
