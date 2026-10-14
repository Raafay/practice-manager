from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = "apps.finance"
    label = "finance"
    verbose_name = "Finance"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import jobs  # noqa: F401
