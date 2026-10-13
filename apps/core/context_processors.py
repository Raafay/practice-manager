from apps.core.models import PracticeSettings


def layout(request):
    """Values the page layout needs on every page."""
    from django.conf import settings

    context = {"practice": PracticeSettings.load(), "sms_enabled": bool(settings.SMS_BACKEND)}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.events.models import Notification

        context["unread_notifications"] = Notification.objects.unread_for(user).count()
        if user.is_staff_kind and getattr(user, "mfa_done", False):
            from apps.comms.models import QueuedMessage

            context["comms_waiting"] = QueuedMessage.objects.filter(
                state=QueuedMessage.State.NEEDS_APPROVAL
            ).count()
    return context
