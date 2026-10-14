from django.apps import AppConfig


class CommsConfig(AppConfig):
    name = "apps.comms"
    label = "comms"
    verbose_name = "Communications"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import delivery

        delivery.connect()
