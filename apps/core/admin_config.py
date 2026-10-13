from django.contrib.admin.apps import AdminConfig


class ControlAdminConfig(AdminConfig):
    """The Django admin at /control/, for the owner only."""

    default_site = "apps.core.admin_site.ControlAdminSite"
