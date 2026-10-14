from django.urls import path

from . import views, views_clearance, views_hmrc, views_letters, views_settings, views_sign

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
    # Engagement letters (staff)
    path(
        "clients/<int:pk>/engagement/", views_letters.EngagementTabView.as_view(), name="engagement"
    ),
    path(
        "clients/<int:pk>/engagement/prepare/", views_letters.PrepareView.as_view(), name="prepare"
    ),
    path(
        "clients/<int:pk>/engagement/<int:letter_pk>/",
        views_letters.LetterView.as_view(),
        name="letter",
    ),
    path(
        "clients/<int:pk>/engagement/<int:letter_pk>/cancel/",
        views_letters.LetterActionView.as_view(action="cancel"),
        name="letter_cancel",
    ),
    path(
        "clients/<int:pk>/engagement/<int:letter_pk>/cancel-link/",
        views_letters.LetterActionView.as_view(action="cancel_link"),
        name="letter_cancel_link",
    ),
    path(
        "settings/engagement-letter/", views_letters.LetterPartsView.as_view(), name="letter_parts"
    ),
    path(
        "settings/engagement-letter/<str:key>/",
        views_letters.LetterPartEditView.as_view(),
        name="letter_part",
    ),
    # Signing: no sign-in, a private link
    path("sign/<str:token>/", views_sign.SignView.as_view(), name="sign"),
    path("sign/<str:token>/pdf/", views_sign.SignPdfView.as_view(), name="sign_pdf"),
    # HMRC authorisations
    path("clients/<int:pk>/hmrc/", views_hmrc.HmrcTabView.as_view(), name="hmrc"),
    path("clients/<int:pk>/hmrc/add/", views_hmrc.AuthorisationAddView.as_view(), name="hmrc_add"),
    path(
        "clients/<int:pk>/hmrc/<int:auth_pk>/",
        views_hmrc.AuthorisationEditView.as_view(),
        name="hmrc_edit",
    ),
    path(
        "clients/<int:pk>/hmrc/<int:auth_pk>/reveal/",
        views_hmrc.AuthorisationRevealView.as_view(),
        name="hmrc_reveal",
    ),
    # Professional clearance
    path(
        "clients/<int:pk>/clearance/start/",
        views_clearance.ClearanceStartView.as_view(),
        name="clearance_start",
    ),
    path(
        "clients/<int:pk>/clearance/<int:req_pk>/",
        views_clearance.ClearanceUpdateView.as_view(),
        name="clearance_update",
    ),
    path(
        "clients/<int:pk>/clearance/<int:req_pk>/chase/",
        views_clearance.ClearanceChaseView.as_view(),
        name="clearance_chase",
    ),
]
