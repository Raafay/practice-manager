from django.apps import AppConfig


class TimekeepingConfig(AppConfig):
    name = "apps.timekeeping"
    label = "timekeeping"
    verbose_name = "Time tracking"
    default_auto_field = "django.db.models.BigAutoField"
