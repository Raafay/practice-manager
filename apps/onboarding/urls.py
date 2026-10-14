from django.urls import path

from . import views, views_settings

app_name = "onboarding"

urlpatterns = [
    path("clients/<int:pk>/onboarding/", views.OnboardingTabView.as_view(), name="tab"),
    path("clients/<int:pk>/onboarding/<int:item_pk>/", views.ItemEditView.as_view(), name="item"),
    path("clients/<int:pk>/make-live/", views.MakeLiveView.as_view(), name="make_live"),
    path(
        "settings/onboarding-checklist/",
        views_settings.ChecklistListView.as_view(),
        name="checklist",
    ),
    path(
        "settings/onboarding-checklist/add/",
        views_settings.ChecklistEditView.as_view(),
        name="checklist_add",
    ),
    path(
        "settings/onboarding-checklist/<int:pk>/edit/",
        views_settings.ChecklistEditView.as_view(),
        name="checklist_edit",
    ),
    path(
        "settings/onboarding-checklist/<int:pk>/delete/",
        views_settings.ChecklistDeleteView.as_view(),
        name="checklist_delete",
    ),
]
