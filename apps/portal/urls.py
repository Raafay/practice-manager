from django.urls import path

from . import views, views_client, views_items, views_public, views_signin, views_staff

app_name = "portal"

urlpatterns = [
    # Portal sign-in and pages (a signed-in client contact)
    path("portal/login/", views_signin.PortalLoginView.as_view(), name="login"),
    path("portal/login/code/", views_signin.PortalCodeView.as_view(), name="login_code"),
    path("portal/logout/", views_signin.portal_logout, name="logout"),
    path("portal/", views.HomeView.as_view(), name="home"),
    path("portal/switch/", views.SwitchView.as_view(), name="switch"),
    path("portal/documents/", views.DocumentsView.as_view(), name="documents"),
    path("portal/documents/upload/", views.UploadView.as_view(), name="upload"),
    path(
        "portal/documents/<uuid:public_id>/",
        views.DocumentDownloadView.as_view(),
        name="document",
    ),
    path("portal/requests/", views.RequestsView.as_view(), name="requests"),
    path("portal/requests/new/", views.RequestNewView.as_view(), name="request_new"),
    path(
        "portal/requests/<uuid:public_id>/",
        views.RequestDetailView.as_view(),
        name="request_detail",
    ),
    path("portal/details/", views.DetailsView.as_view(), name="details"),
    path("portal/items/<uuid:public_id>/", views_items.ItemView.as_view(), name="item"),
    path(
        "portal/items/<uuid:public_id>/upload/",
        views_items.ItemUploadView.as_view(),
        name="item_upload",
    ),
    path(
        "portal/items/<uuid:public_id>/everything/",
        views_items.EverythingView.as_view(),
        name="item_everything",
    ),
    path(
        "portal/items/<uuid:public_id>/approve/",
        views_items.ApproveView.as_view(),
        name="item_approve",
    ),
    path("portal/items/<uuid:public_id>/form/", views_items.ItemFormView.as_view(), name="form"),
    # The request link: no sign-in
    path("r/<str:token>/", views_public.RequestFormView.as_view(), name="request_form"),
    path("r/<str:token>/thanks/", views_public.RequestThanksView.as_view(), name="request_thanks"),
    # Staff: the inbox
    path("requests/", views_staff.InboxView.as_view(), name="inbox"),
    path("requests/log/", views_staff.LogRequestView.as_view(), name="inbox_log"),
    path("requests/<int:pk>/", views_staff.RequestDetailView.as_view(), name="inbox_detail"),
    path("requests/<int:pk>/convert/", views_staff.ConvertView.as_view(), name="inbox_convert"),
    path("requests/<int:pk>/link/", views_staff.LinkTaskView.as_view(), name="inbox_link"),
    path("requests/<int:pk>/reply/", views_staff.ReplyView.as_view(), name="inbox_reply"),
    path("requests/<int:pk>/close/", views_staff.CloseView.as_view(), name="inbox_close"),
    path("requests/<int:pk>/spam/", views_staff.SpamView.as_view(), name="inbox_spam"),
    path("requests/<int:pk>/reopen/", views_staff.ReopenView.as_view(), name="inbox_reopen"),
    path("requests/<int:pk>/client/", views_staff.SetClientView.as_view(), name="inbox_client"),
    path(
        "requests/<int:pk>/files/<uuid:public_id>/",
        views_staff.AttachmentView.as_view(),
        name="inbox_file",
    ),
    # Staff: on a client
    path(
        "clients/<int:pk>/requests/",
        views_client.ClientRequestsView.as_view(),
        name="client_requests",
    ),
    path(
        "clients/<int:pk>/requests/replace-link/",
        views_client.ReplaceLinkView.as_view(),
        name="replace_link",
    ),
    path(
        "clients/<int:pk>/contacts/<int:link_pk>/portal-invite/",
        views_client.InviteView.as_view(),
        name="invite",
    ),
    path(
        "clients/<int:pk>/contacts/<int:link_pk>/portal-withdraw/",
        views_client.WithdrawView.as_view(),
        name="withdraw",
    ),
    path(
        "clients/<int:pk>/portal-items/<int:item_pk>/cancel/",
        views_client.CancelItemView.as_view(),
        name="item_cancel",
    ),
    path(
        "tasks/<int:pk>/ask-upload/", views_client.AskUploadView.as_view(), name="task_ask_upload"
    ),
    path(
        "tasks/<int:pk>/ask-approve/",
        views_client.AskApproveView.as_view(),
        name="task_ask_approve",
    ),
    path("portal-forms/<int:pk>/review/", views_client.FormReviewView.as_view(), name="review"),
    path(
        "portal-forms/<int:pk>/review/act/",
        views_client.FormReviewActionView.as_view(),
        name="review_act",
    ),
]
