from django.urls import path

from . import views

app_name = "companieshouse"

urlpatterns = [
    path("companies-house/add/", views.AddSearchView.as_view(), name="add"),
    path("companies-house/add/<str:number>/", views.AddPreviewView.as_view(), name="preview"),
    path("clients/<int:pk>/companies-house/", views.CompaniesHouseTabView.as_view(), name="tab"),
    path("clients/<int:pk>/companies-house/sync/", views.SyncNowView.as_view(), name="sync"),
    path("clients/<int:pk>/companies-house/fill-in/", views.FillInView.as_view(), name="fill_in"),
    path("settings/integrations/", views.IntegrationsView.as_view(), name="integrations"),
]
