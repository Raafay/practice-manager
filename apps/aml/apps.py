from django.apps import AppConfig


class AmlConfig(AppConfig):
    name = "apps.aml"
    label = "aml"
    verbose_name = "Anti-money-laundering"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import jobs, signals  # noqa: F401
