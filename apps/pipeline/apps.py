from django.apps import AppConfig


class PipelineConfig(AppConfig):
    name = "apps.pipeline"
    label = "pipeline"
    verbose_name = "Prospects and proposals"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import jobs, signals  # noqa: F401
