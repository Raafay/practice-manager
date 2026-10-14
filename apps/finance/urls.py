from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("finance/fees/", views.FeesView.as_view(), name="fees"),
    path("finance/invoices/", views.InvoicesView.as_view(), name="invoices"),
    path("finance/invoices/chase/", views.ChaseView.as_view(), name="chase"),
    path("finance/targets/", views.TargetsView.as_view(), name="targets"),
    path("finance/forecast/", views.ForecastView.as_view(), name="forecast"),
    path("finance/summary/", views.SummaryView.as_view(), name="summary"),
    path("finance/settings/", views.SettingsView.as_view(), name="settings"),
    path("finance/xero/contacts/", views.MatchingView.as_view(), name="matching"),
    path(
        "finance/xero/contacts/<int:pk>/confirm/",
        views.MatchActionView.as_view(action="confirm"),
        name="match_confirm",
    ),
    path(
        "finance/xero/contacts/<int:pk>/unmatch/",
        views.MatchActionView.as_view(action="unmatch"),
        name="match_unmatch",
    ),
    path(
        "finance/xero/contacts/<int:pk>/ignore/",
        views.MatchActionView.as_view(action="ignore"),
        name="match_ignore",
    ),
    path("integrations/xero/connect/", views.XeroConnectView.as_view(), name="xero_connect"),
    path("integrations/xero/callback", views.XeroCallbackView.as_view(), name="xero_callback"),
    path(
        "integrations/xero/disconnect/", views.XeroDisconnectView.as_view(), name="xero_disconnect"
    ),
    path("integrations/xero/sync/", views.XeroSyncNowView.as_view(), name="xero_sync"),
    path("clients/<int:pk>/fees/", views.ClientFeesView.as_view(), name="client_fees"),
    path("clients/<int:pk>/xero/send/", views.SendToXeroView.as_view(), name="send_to_xero"),
]
