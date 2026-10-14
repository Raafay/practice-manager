from django.urls import path

from . import views, views_proposals, views_public, views_settings

app_name = "pipeline"

urlpatterns = [
    path("prospects/", views.ProspectsView.as_view(), name="prospects"),
    path("prospects/new/", views.ProspectNewView.as_view(), name="prospect_new"),
    path("prospects/<int:pk>/move/", views.ProspectMoveView.as_view(), name="move"),
    path("clients/<int:pk>/sales/edit/", views.SalesEditView.as_view(), name="sales_edit"),
    path("clients/<int:pk>/meetings/add/", views.MeetingAddView.as_view(), name="meeting_add"),
    # Proposals (staff)
    path(
        "clients/<int:pk>/proposals/new/",
        views_proposals.ProposalCreateView.as_view(),
        name="proposal_new",
    ),
    path(
        "clients/<int:pk>/proposals/<int:proposal_pk>/",
        views_proposals.ProposalDetailView.as_view(),
        name="proposal",
    ),
    path(
        "clients/<int:pk>/proposals/<int:proposal_pk>/send/",
        views_proposals.ProposalComposeView.as_view(),
        name="proposal_send",
    ),
    path(
        "clients/<int:pk>/proposals/<int:proposal_pk>/withdraw/",
        views_proposals.ProposalActionView.as_view(action="withdraw"),
        name="proposal_withdraw",
    ),
    path(
        "clients/<int:pk>/proposals/<int:proposal_pk>/cancel-link/",
        views_proposals.ProposalActionView.as_view(action="cancel_link"),
        name="proposal_cancel_link",
    ),
    # Settings
    path("settings/pipeline-stages/", views_settings.StageListView.as_view(), name="stages"),
    path("settings/pipeline-stages/add/", views_settings.StageEditView.as_view(), name="stage_add"),
    path(
        "settings/pipeline-stages/<int:pk>/edit/",
        views_settings.StageEditView.as_view(),
        name="stage_edit",
    ),
    path(
        "settings/pipeline-stages/<int:pk>/delete/",
        views_settings.StageDeleteView.as_view(),
        name="stage_delete",
    ),
    path("settings/pipeline-rules/", views_settings.PipelineSettingsView.as_view(), name="rules"),
    # The client's proposal page: no sign-in, reached by an action link
    path("proposal/<str:token>/", views_public.ProposalPageView.as_view(), name="proposal_page"),
    path("proposal/<str:token>/pdf/", views_public.ProposalPdfView.as_view(), name="proposal_pdf"),
]
