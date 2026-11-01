from django.urls import path

from . import views

app_name = "creditsafe"

urlpatterns = [
    path("clients/<int:pk>/credit/check/", views.CheckView.as_view(), name="check"),
]
