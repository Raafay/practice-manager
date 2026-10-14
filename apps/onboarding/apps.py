from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    name = "apps.onboarding"
    label = "onboarding"
    verbose_name = "Onboarding"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import jobs, signals  # noqa: F401
