from django.contrib import admin

from .models import PracticeSettings


@admin.register(PracticeSettings)
class PracticeSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
