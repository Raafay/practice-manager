from django.contrib import admin

from .models import Invitation, Role, Team, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "kind", "role", "is_active"]
    list_filter = ["kind", "role", "is_active"]
    search_fields = ["name", "email"]
    exclude = ["password"]
    readonly_fields = ["last_login", "created_at", "updated_at"]
    filter_horizontal = ["teams"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "order"]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "name", "role", "expires_at", "accepted_at", "cancelled_at"]
    readonly_fields = ["token_hash"]
