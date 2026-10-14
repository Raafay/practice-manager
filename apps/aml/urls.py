from django.urls import path

from . import views, views_register, views_settings

app_name = "aml"

urlpatterns = [
    path("clients/<int:pk>/risk/", views.RiskTabView.as_view(), name="tab"),
    path(
        "clients/<int:pk>/risk/identity/<int:check_pk>/",
        views.IdentityEditView.as_view(),
        name="identity",
    ),
    path("clients/<int:pk>/risk/people/add/", views.PersonAddView.as_view(), name="person_add"),
    path(
        "clients/<int:pk>/risk/people/<int:check_pk>/remove/",
        views.PersonRemoveView.as_view(),
        name="person_remove",
    ),
    path("clients/<int:pk>/risk/start/", views.AssessmentStartView.as_view(), name="start"),
    path(
        "clients/<int:pk>/risk/assessments/<int:assessment_pk>/",
        views.AssessmentView.as_view(),
        name="assessment",
    ),
    path(
        "clients/<int:pk>/risk/assessments/<int:assessment_pk>/approve/",
        views.AssessmentApproveView.as_view(),
        name="approve",
    ),
    path(
        "clients/<int:pk>/risk/assessments/<int:assessment_pk>/send-back/",
        views.AssessmentSendBackView.as_view(),
        name="send_back",
    ),
    # Settings
    path("settings/risk-questions/", views_settings.QuestionListView.as_view(), name="questions"),
    path(
        "settings/risk-questions/add/",
        views_settings.QuestionEditView.as_view(),
        name="question_add",
    ),
    path(
        "settings/risk-questions/<int:pk>/edit/",
        views_settings.QuestionEditView.as_view(),
        name="question_edit",
    ),
    path(
        "settings/risk-questions/<int:pk>/toggle/",
        views_settings.QuestionToggleView.as_view(),
        name="question_toggle",
    ),
    path("settings/aml-bands/", views_settings.BandsView.as_view(), name="bands"),
    path("settings/aml-records/", views_settings.RecordsView.as_view(), name="records"),
    path(
        "settings/aml-records/training/add/",
        views_settings.TrainingAddView.as_view(),
        name="training_add",
    ),
    path(
        "settings/aml-records/training/<int:pk>/delete/",
        views_settings.TrainingDeleteView.as_view(),
        name="training_delete",
    ),
    path(
        "settings/aml-records/policy/add/",
        views_settings.PolicyAddView.as_view(),
        name="policy_add",
    ),
    path(
        "settings/aml-records/policy/<int:pk>/",
        views_settings.PolicyDownloadView.as_view(),
        name="policy",
    ),
    path(
        "settings/aml-records/policy/<int:pk>/delete/",
        views_settings.PolicyDeleteView.as_view(),
        name="policy_delete",
    ),
    path("reports/aml-register/", views_register.RegisterView.as_view(), name="register"),
    path(
        "reports/aml-register/export/",
        views_register.RegisterExportView.as_view(),
        name="register_export",
    ),
]
