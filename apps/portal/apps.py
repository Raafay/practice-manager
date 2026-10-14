from django.apps import AppConfig


class PortalConfig(AppConfig):
    name = "apps.portal"
    label = "portal"
    verbose_name = "Portal and requests"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import links, signals  # noqa: F401
