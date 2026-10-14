from django.apps import AppConfig


class ImportsConfig(AppConfig):
    name = "apps.imports"
    label = "imports"
    verbose_name = "Imports"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import jobs  # noqa: F401
