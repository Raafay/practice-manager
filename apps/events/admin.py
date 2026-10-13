from django.contrib import admin

from .models import ActivityEvent, Notification


@admin.register(ActivityEvent)
class ActivityEventAdmin(admin.ModelAdmin):
    """Read only. Events are never edited or deleted."""

    list_display = ["created_at", "actor_label", "verb", "summary"]
    list_filter = ["verb"]
    search_fields = ["summary", "actor_label"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "message", "read_at"]
