from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("settings/audit/", views.AuditLogView.as_view(), name="audit_log"),
    path("notifications/", views.NotificationListView.as_view(), name="notifications"),
    path("notifications/read-all/", views.MarkAllReadView.as_view(), name="notifications_read_all"),
    path(
        "notifications/<int:pk>/open/",
        views.OpenNotificationView.as_view(),
        name="notification_open",
    ),
]
