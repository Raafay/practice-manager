from allauth.mfa.models import Authenticator
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.core.htmx import htmx_redirect
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from . import services
from .forms import (
    AcceptInvitationForm,
    ExtraRightsForm,
    InviteForm,
    ProfileForm,
    RoleForm,
    RoleRightsForm,
    TeamForm,
    TeamsForm,
)
from .models import Invitation, Role, Team, User
from .rights import RIGHTS


class ManageUsersMixin(CapabilityRequiredMixin):
    required_rights = ("users.manage",)


def staff_with_mfa_flag():
    has_totp = Authenticator.objects.filter(user=OuterRef("pk"), type=Authenticator.Type.TOTP)
    return (
        User.objects.staff()
        .annotate(has_mfa=Exists(has_totp))
        .prefetch_related(Prefetch("teams", queryset=Team.objects.order_by("name")))
    )


class UserListView(ManageUsersMixin, TemplateView):
    template_name = "accounts/user_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        show = self.request.GET.get("show", "active")
        users = staff_with_mfa_flag().order_by("name")
        context["show"] = show
        context["users"] = users.filter(is_active=show != "inactive")
        context["inactive_count"] = User.objects.staff().filter(is_active=False).count()
        context["invitations"] = Invitation.objects.pending().select_related("role", "invited_by")
        return context


class InviteView(ManageUsersMixin, View):
    template_name = "accounts/invite.html"
    partial_template_name = "accounts/_invite_form.html"

    def render_form(self, request, form, status=200):
        template = self.partial_template_name if request.htmx else self.template_name
        return render(request, template, {"form": form}, status=status)

    def get(self, request):
        initial = {"role": Role.objects.filter(slug=Role.STAFF).first()}
        return self.render_form(request, InviteForm(initial=initial))

    def post(self, request):
        form = InviteForm(request.POST)
        if not form.is_valid():
            return self.render_form(request, form, status=422)
        invitation = services.invite_user(
            request.user,
            email=form.cleaned_data["email"],
            name=form.cleaned_data["name"],
            role=form.cleaned_data["role"],
            request=request,
        )
        messages.success(
            request,
            f"Invitation sent to {invitation.email}. The link works once and lasts 72 hours.",
        )
        return htmx_redirect(request, reverse("accounts:users"))


class CancelInvitationView(ManageUsersMixin, View):
    def post(self, request, pk):
        invitation = get_object_or_404(Invitation, pk=pk)
        services.cancel_invitation(request.user, invitation)
        messages.success(request, f"The invitation for {invitation.email} was cancelled.")
        return redirect("accounts:users")


class UserDetailView(ManageUsersMixin, TemplateView):
    template_name = "accounts/user_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        person = get_object_or_404(staff_with_mfa_flag(), pk=self.kwargs["pk"])
        context.update(
            person=person,
            role_form=RoleForm(initial={"role": person.role}),
            rights_form=ExtraRightsForm(initial={"extra_rights": person.extra_rights}),
            teams_form=TeamsForm(initial={"teams": list(person.teams.all())}),
            role_rights=person.role.effective_rights() if person.role else set(),
            rights=RIGHTS,
        )
        return context


class UserActionView(ManageUsersMixin, View):
    """Base for the POST-only actions on one user."""

    def get_person(self):
        return get_object_or_404(User.objects.staff(), pk=self.kwargs["pk"])

    def back(self, person):
        return redirect("accounts:user_detail", pk=person.pk)

    def post(self, request, pk):
        person = self.get_person()
        try:
            self.act(request, person)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return self.back(person)

    def act(self, request, person):  # pragma: no cover - overridden
        raise NotImplementedError


class UserRoleView(UserActionView):
    require_reauth = True

    def act(self, request, person):
        form = RoleForm(request.POST)
        if form.is_valid():
            services.change_role(request.user, person, form.cleaned_data["role"])
            messages.success(request, f"{person} is now {form.cleaned_data['role']}.")


class UserRightsView(UserActionView):
    require_reauth = True

    def act(self, request, person):
        form = ExtraRightsForm(request.POST)
        if form.is_valid():
            services.set_extra_rights(request.user, person, form.cleaned_data["extra_rights"])
            messages.success(request, f"Single rights for {person} saved.")


class UserTeamsView(UserActionView):
    def act(self, request, person):
        form = TeamsForm(request.POST)
        if form.is_valid():
            services.set_user_teams(request.user, person, form.cleaned_data["teams"])
            messages.success(request, f"Teams for {person} saved.")


class ResetMfaView(UserActionView):
    require_reauth = True

    def act(self, request, person):
        services.reset_mfa(request.user, person)
        messages.success(
            request,
            f"Two-factor was reset for {person}. They will set it up again when they next sign in.",
        )


class DeactivateUserView(UserActionView):
    def act(self, request, person):
        services.deactivate_user(request.user, person)
        messages.success(request, f"{person} was deactivated and can no longer sign in.")


class ReactivateUserView(UserActionView):
    def act(self, request, person):
        services.reactivate_user(request.user, person)
        messages.success(request, f"{person} was reactivated.")


class TeamListView(ManageUsersMixin, TemplateView):
    template_name = "accounts/team_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_members = Prefetch(
            "members", queryset=User.objects.filter(is_active=True).order_by("name")
        )
        context["teams"] = Team.objects.annotate(size=Count("members")).prefetch_related(
            active_members
        )
        return context


class TeamFormView(ManageUsersMixin, View):
    template_name = "accounts/team_form.html"

    def get_team(self):
        pk = self.kwargs.get("pk")
        return get_object_or_404(Team, pk=pk) if pk else Team()

    def get(self, request, pk=None):
        return render(request, self.template_name, {"form": TeamForm(instance=self.get_team())})

    def post(self, request, pk=None):
        form = TeamForm(request.POST, instance=self.get_team())
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=422)
        team = services.save_team(request.user, form)
        messages.success(request, f"Team {team} saved.")
        return redirect("accounts:teams")


class TeamDeleteView(ManageUsersMixin, View):
    def post(self, request, pk):
        team = get_object_or_404(Team, pk=pk)
        services.delete_team(request.user, team)
        messages.success(request, f"Team {team} deleted.")
        return redirect("accounts:teams")


class RolesView(ManageUsersMixin, View):
    template_name = "accounts/roles.html"

    def dispatch(self, request, *args, **kwargs):
        # Viewing the ticks needs no password. Saving them does.
        self.require_reauth = request.method == "POST"
        return super().dispatch(request, *args, **kwargs)

    def context(self, form, roles):
        rows = []
        for right, label in RIGHTS.items():
            cells = []
            for role in roles:
                if role.is_owner_role:
                    cells.append({"role": role, "owner": True})
                else:
                    cells.append(
                        {"role": role, "field": form[RoleRightsForm.field_name(role, right)]}
                    )
            rows.append({"right": right, "label": label, "cells": cells})
        return {"form": form, "roles": roles, "rows": rows}

    def get(self, request):
        roles = list(Role.objects.all())
        return render(request, self.template_name, self.context(RoleRightsForm(roles=roles), roles))

    def post(self, request):
        roles = list(Role.objects.all())
        form = RoleRightsForm(request.POST, roles=roles)
        if not form.is_valid():  # pragma: no cover - tick boxes cannot be invalid
            return render(request, self.template_name, self.context(form, roles), status=422)
        for role in form.roles:
            services.set_role_rights(request.user, role, form.rights_for(role))
        messages.success(request, "Role rights saved.")
        return redirect("accounts:roles")


class ProfileView(StaffRequiredMixin, View):
    template_name = "accounts/profile.html"

    def render_page(self, request, form, status=200):
        return render(
            request, self.template_name, {"form": form, "person": request.user}, status=status
        )

    def get(self, request):
        return self.render_page(request, ProfileForm(instance=request.user))

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if not form.is_valid():
            return self.render_page(request, form, status=422)
        services.update_profile(request.user, form)
        messages.success(request, "Your profile was saved.")
        return redirect("accounts:profile")


class AcceptInvitationView(View):
    """Public: the token is the only key. It works once and expires after 72 hours."""

    template_name = "accounts/accept_invitation.html"

    def get_invitation(self, token):
        invitation = Invitation.from_token(token)
        if invitation is None:
            raise Http404
        return invitation

    def get(self, request, token):
        invitation = self.get_invitation(token)
        if request.user.is_authenticated:
            return render(request, "accounts/invitation_signed_in.html", status=409)
        form = AcceptInvitationForm(invitation=invitation) if invitation.is_usable else None
        return render(request, self.template_name, {"invitation": invitation, "form": form})

    def post(self, request, token):
        invitation = self.get_invitation(token)
        if request.user.is_authenticated:
            return render(request, "accounts/invitation_signed_in.html", status=409)
        if not invitation.is_usable:
            return render(
                request, self.template_name, {"invitation": invitation, "form": None}, status=410
            )
        form = AcceptInvitationForm(request.POST, invitation=invitation)
        if not form.is_valid():
            return render(
                request, self.template_name, {"invitation": invitation, "form": form}, status=422
            )
        try:
            services.accept_invitation(invitation, form.cleaned_data["password1"], request=request)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("account_login")
        messages.success(request, "Your account is ready. Now set up two-factor sign-in.")
        return redirect("mfa_activate_totp")
