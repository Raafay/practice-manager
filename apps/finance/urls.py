from django.urls import path
from django.views.generic import RedirectView

app_name = "finance"

urlpatterns = [
    path("finance/fees/", RedirectView.as_view(url="/"), name="fees"),
]
