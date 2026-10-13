from apps.core.models import PracticeSettings


def layout(request):
    """Values the page layout needs on every page."""
    context = {"practice": PracticeSettings.load()}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.events.models import Notification

        context["unread_notifications"] = Notification.objects.unread_for(user).count()
    return context
