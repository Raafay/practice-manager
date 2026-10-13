from django.apps import AppConfig


class ServicesConfig(AppConfig):
    name = "apps.services"
    label = "services"
    verbose_name = "Services and deadlines"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401 - connects the receivers
