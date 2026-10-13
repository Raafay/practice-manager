from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("invite/<str:token>/", views.AcceptInvitationView.as_view(), name="accept_invitation"),
    path("settings/users/", views.UserListView.as_view(), name="users"),
    path("settings/users/invite/", views.InviteView.as_view(), name="invite"),
    path(
        "settings/users/invitations/<int:pk>/cancel/",
        views.CancelInvitationView.as_view(),
        name="cancel_invitation",
    ),
    path("settings/users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("settings/users/<int:pk>/role/", views.UserRoleView.as_view(), name="user_role"),
    path("settings/users/<int:pk>/rights/", views.UserRightsView.as_view(), name="user_rights"),
    path("settings/users/<int:pk>/teams/", views.UserTeamsView.as_view(), name="user_teams"),
    path(
        "settings/users/<int:pk>/reset-two-factor/",
        views.ResetMfaView.as_view(),
        name="user_reset_mfa",
    ),
    path(
        "settings/users/<int:pk>/deactivate/",
        views.DeactivateUserView.as_view(),
        name="user_deactivate",
    ),
    path(
        "settings/users/<int:pk>/reactivate/",
        views.ReactivateUserView.as_view(),
        name="user_reactivate",
    ),
    path("settings/teams/", views.TeamListView.as_view(), name="teams"),
    path("settings/teams/new/", views.TeamFormView.as_view(), name="team_create"),
    path("settings/teams/<int:pk>/", views.TeamFormView.as_view(), name="team_edit"),
    path("settings/teams/<int:pk>/delete/", views.TeamDeleteView.as_view(), name="team_delete"),
    path("settings/roles/", views.RolesView.as_view(), name="roles"),
]
