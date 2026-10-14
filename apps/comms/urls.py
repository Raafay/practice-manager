from django.urls import path

from . import delivery, views, views_settings

app_name = "comms"

urlpatterns = [
    # Delivery reports from the email provider. Public, checked by a shared secret.
    path("email/events/", delivery.delivery_webhook, name="webhook"),
    path("messages/", views.QueueView.as_view(), name="queue"),
    path("messages/bulk-approve/", views.BulkApproveView.as_view(), name="bulk_approve"),
    path("messages/pause/", views.PauseView.as_view(), name="pause"),
    path("messages/email-clients/", views.BulkEmailView.as_view(), name="bulk_email"),
    path("messages/<int:pk>/", views.MessageView.as_view(), name="message"),
    path("clients/<int:pk>/compose/", views.ComposeView.as_view(), name="compose"),
    path("clients/<int:pk>/log-email/", views.LogEmailView.as_view(), name="log_email"),
    path("clients/<int:pk>/letter/", views.LetterView.as_view(), name="letter"),
    path("clients/<int:pk>/sms/", views.SmsView.as_view(), name="sms"),
    path("settings/templates/", views_settings.TemplateListView.as_view(), name="templates"),
    path("settings/templates/new/", views_settings.TemplateEditView.as_view(), name="template_add"),
    path(
        "settings/templates/<int:pk>/",
        views_settings.TemplateEditView.as_view(),
        name="template_edit",
    ),
    path(
        "settings/templates/<int:pk>/delete/",
        views_settings.TemplateDeleteView.as_view(),
        name="template_delete",
    ),
    path(
        "settings/templates/<int:pk>/toggle/",
        views_settings.TemplateToggleView.as_view(),
        name="template_toggle",
    ),
    path("settings/reminders/", views_settings.ScheduleListView.as_view(), name="reminders"),
    path(
        "settings/reminders/<int:pk>/",
        views_settings.ScheduleEditView.as_view(),
        name="reminder_edit",
    ),
    path(
        "settings/reminders/<int:pk>/toggle/",
        views_settings.ScheduleToggleView.as_view(),
        name="reminder_toggle",
    ),
]
