from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = "apps.jobs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Each app that owns jobs registers them in its own jobs.py.
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("jobs")
