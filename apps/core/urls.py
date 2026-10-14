from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Answered by HealthCheckMiddleware; the address is listed here so it is known.
    path("healthz/", views.healthz, name="healthz"),
    path("styleguide/", views.StyleguideView.as_view(), name="styleguide"),
    path(
        "styleguide/demo/<slug:kind>/", views.StyleguideDemoView.as_view(), name="styleguide_demo"
    ),
    path("settings/", views.SettingsIndexView.as_view(), name="settings"),
    path("settings/practice/", views.PracticeSettingsView.as_view(), name="practice_settings"),
    path("settings/practice/logo/", views.PracticeLogoView.as_view(), name="practice_logo"),
    path("settings/security/", views.SecuritySettingsView.as_view(), name="security_settings"),
]
