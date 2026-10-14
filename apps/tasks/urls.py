from django.urls import path

from . import views, views_settings

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.TaskListView.as_view(), name="list"),
    path("tasks/new/", views.TaskCreateView.as_view(), name="new"),
    path("tasks/client-options/", views.ClientOptionsView.as_view(), name="client_options"),
    path("tasks/bulk/", views.BulkView.as_view(), name="bulk"),
    path("tasks/board/move/", views.BoardMoveView.as_view(), name="board_move"),
    path("tasks/calendar/move/", views.CalendarMoveView.as_view(), name="calendar_move"),
    path("tasks/views/save/", views.SavedViewCreateView.as_view(), name="view_save"),
    path(
        "tasks/views/<int:pk>/default/", views.SavedViewDefaultView.as_view(), name="view_default"
    ),
    path("tasks/views/<int:pk>/delete/", views.SavedViewDeleteView.as_view(), name="view_delete"),
    path("tasks/<int:pk>/", views.TaskDetailView.as_view(), name="detail"),
    path("tasks/<int:pk>/field/<str:field>/", views.TaskFieldView.as_view(), name="field"),
    path(
        "tasks/<int:pk>/complete/", views.TaskActionView.as_view(action="complete"), name="complete"
    ),
    path("tasks/<int:pk>/cancel/", views.TaskActionView.as_view(action="cancel"), name="cancel"),
    path("tasks/<int:pk>/star/", views.TaskActionView.as_view(action="star"), name="star"),
    path("tasks/<int:pk>/follow/", views.TaskActionView.as_view(action="follow"), name="follow"),
    path("tasks/<int:pk>/step/", views.StepPickView.as_view(), name="step_pick"),
    path("tasks/<int:pk>/steps/<int:step_pk>/toggle/", views.StepToggleView.as_view(), name="step"),
    path("tasks/<int:pk>/comment/", views.CommentView.as_view(), name="comment"),
    path("tasks/<int:pk>/description/", views.DescriptionView.as_view(), name="description"),
    path("tasks/<int:pk>/attach/", views.AttachView.as_view(), name="attach"),
    path("clients/<int:pk>/tasks/", views.ClientTasksView.as_view(), name="client_tasks"),
    # Settings
    path("settings/task-statuses/", views_settings.StatusListView.as_view(), name="statuses"),
    path("settings/task-statuses/add/", views_settings.StatusEditView.as_view(), name="status_add"),
    path(
        "settings/task-statuses/<int:pk>/edit/",
        views_settings.StatusEditView.as_view(),
        name="status_edit",
    ),
    path(
        "settings/task-statuses/<int:pk>/delete/",
        views_settings.StatusDeleteView.as_view(),
        name="status_delete",
    ),
    path(
        "settings/task-statuses/<int:pk>/move/<str:direction>/",
        views_settings.StatusMoveView.as_view(),
        name="status_move",
    ),
    path(
        "settings/task-statuses/<int:pk>/merge/",
        views_settings.StatusMergeView.as_view(),
        name="status_merge",
    ),
    path("settings/task-categories/", views_settings.CategoryListView.as_view(), name="categories"),
    path(
        "settings/task-categories/add/",
        views_settings.CategoryEditView.as_view(),
        name="category_add",
    ),
    path(
        "settings/task-categories/<int:pk>/edit/",
        views_settings.CategoryEditView.as_view(),
        name="category_edit",
    ),
    path(
        "settings/task-categories/<int:pk>/delete/",
        views_settings.CategoryDeleteView.as_view(),
        name="category_delete",
    ),
    path(
        "settings/task-categories/<int:pk>/move/<str:direction>/",
        views_settings.CategoryMoveView.as_view(),
        name="category_move",
    ),
    path(
        "settings/task-categories/<int:pk>/merge/",
        views_settings.CategoryMergeView.as_view(),
        name="category_merge",
    ),
    path(
        "settings/services/<int:pk>/templates/",
        views_settings.ServiceTemplatesView.as_view(),
        name="service_templates",
    ),
    path(
        "settings/services/<int:pk>/templates/add/",
        views_settings.TemplateEditView.as_view(),
        name="template_add",
    ),
    path(
        "settings/task-templates/<int:template_pk>/edit/",
        views_settings.TemplateEditView.as_view(),
        name="template_edit",
    ),
]
