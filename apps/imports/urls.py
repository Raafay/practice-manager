from django.urls import path

from . import views

app_name = "imports"

urlpatterns = [
    path("settings/import/", views.ImportIndexView.as_view(), name="index"),
    path("settings/import/<int:pk>/match/", views.MatchView.as_view(), name="match"),
    path("settings/import/<int:pk>/check/", views.CheckView.as_view(), name="check"),
    path("settings/import/<int:pk>/", views.RunView.as_view(), name="run"),
    path("settings/import/<int:pk>/failures/", views.FailuresView.as_view(), name="failures"),
    path("settings/import/<int:pk>/undo/", views.UndoView.as_view(), name="undo"),
    path("settings/import/<int:pk>/fetch/", views.FetchView.as_view(), name="fetch"),
    path("settings/import/<int:pk>/progress/", views.ProgressView.as_view(), name="progress"),
    path(
        "settings/import/matchings/<int:pk>/delete/",
        views.MatchingDeleteView.as_view(),
        name="matching_delete",
    ),
    path("settings/import/clear-deadlines/", views.HelperView.as_view(), name="helper"),
]
