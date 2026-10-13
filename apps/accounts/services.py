"""Business rules for users, roles, teams and invitations. Every change is recorded."""

from django.contrib.auth import login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps import events
from apps.events.services import changes

from .models import Invitation, LastOwnerError, Role, Team, User
from .rights import RIGHTS


def _require(actor, right: str) -> None:
    if actor is None or not actor.can(right):
        raise PermissionDenied


# Invitations


def invite_user(actor, *, email: str, name: str, role: Role, request=None) -> Invitation:
    """Create an invitation and email the link straight to the person (never queued)."""
    _require(actor, "users.manage")
    with transaction.atomic():
        invitation, raw_token = Invitation.issue(
            email=email, name=name, role=role, invited_by=actor
        )
        events.record(
            actor,
            "user.invited",
            f"{actor} invited {name} ({email}) as {role}.",
            target=invitation,
            email=email,
            role=role.name,
        )
    path = reverse("accounts:accept_invitation", args=[raw_token])
    link = request.build_absolute_uri(path) if request else path
    context = {"invitation": invitation, "link": link, "invited_by": actor}
    send_mail(
        subject="You have been invited to Practice Manager",
        message=render_to_string("accounts/email/invitation.txt", context),
        from_email=None,
        recipient_list=[invitation.email],
    )
    return invitation


def cancel_invitation(actor, invitation: Invitation) -> None:
    _require(actor, "users.manage")
    if not invitation.is_usable:
        return
    invitation.cancelled_at = timezone.now()
    invitation.save(update_fields=["cancelled_at", "updated_at"])
    events.record(
        actor,
        "user.invitation_cancelled",
        f"{actor} cancelled the invitation for {invitation.email}.",
        target=invitation,
    )


def accept_invitation(invitation: Invitation, password: str, request=None) -> User:
    """Create the staff account and spend the link. Signs the person in when given a request."""
    with transaction.atomic():
        locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if not locked.is_usable:
            raise ValidationError(
                "This invitation link has already been used, has expired or was cancelled."
            )
        if User.objects.filter(email__iexact=locked.email).exists():
            raise ValidationError("Someone already has an account with this email address.")
        user = User.objects.create_user(
            locked.email, password, name=locked.name, role=locked.role, kind=User.Kind.STAFF
        )
        locked.accepted_at = timezone.now()
        locked.accepted_user = user
        locked.save(update_fields=["accepted_at", "accepted_user", "updated_at"])
        events.record(
            user, "user.invitation_accepted", f"{user} accepted their invitation.", target=user
        )
    if request is not None:
        login(request, user, backend="allauth.account.auth_backends.AuthenticationBackend")
    return user


# Roles and rights


def change_role(actor, user: User, role: Role) -> None:
    _require(actor, "users.manage")
    old = user.role
    if old == role:
        return
    user.role = role
    try:
        user.save(update_fields=["role", "updated_at"])
    except LastOwnerError:
        user.role = old
        raise
    events.record(
        actor,
        "user.role_changed",
        f"{actor} changed {user}'s role from {old or 'none'} to {role}.",
        target=user,
        role={"old": str(old) if old else None, "new": str(role)},
    )


def set_extra_rights(actor, user: User, rights: list[str]) -> None:
    _require(actor, "users.manage")
    new = sorted(set(rights) & set(RIGHTS))
    old = sorted(user.extra_rights or [])
    if new == old:
        return
    user.extra_rights = new
    user.save(update_fields=["extra_rights", "updated_at"])
    events.record(
        actor,
        "user.rights_changed",
        f"{actor} changed the single rights granted to {user}.",
        target=user,
        added=sorted(set(new) - set(old)),
        removed=sorted(set(old) - set(new)),
    )


def set_role_rights(actor, role: Role, rights: list[str]) -> None:
    _require(actor, "users.manage")
    if role.is_owner_role:
        raise ValidationError("The Owner role always has every right.")
    new = [right for right in RIGHTS if right in set(rights)]
    old = list(role.rights)
    if set(new) == set(old):
        return
    role.rights = new
    role.save(update_fields=["rights", "updated_at"])
    events.record(
        actor,
        "role.rights_changed",
        f"{actor} changed the rights of the {role} role.",
        target=role,
        added=sorted(set(new) - set(old)),
        removed=sorted(set(old) - set(new)),
    )


# Teams


def set_user_teams(actor, user: User, teams) -> None:
    _require(actor, "users.manage")
    old = sorted(team.name for team in user.teams.all())
    user.teams.set(teams)
    new = sorted(team.name for team in user.teams.all())
    if old != new:
        events.record(
            actor,
            "user.teams_changed",
            f"{actor} changed {user}'s teams.",
            target=user,
            teams={"old": old, "new": new},
        )


def save_team(actor, form) -> Team:
    _require(actor, "users.manage")
    creating = form.instance.pk is None
    before = {"name": form.initial.get("name"), "description": form.initial.get("description")}
    before_members = (
        sorted(str(user) for user in form.instance.members.all()) if not creating else []
    )
    with transaction.atomic():
        team = form.save()
        team.members.set(form.cleaned_data["members"])
    after_members = sorted(str(user) for user in team.members.all())
    if creating:
        events.record(
            actor,
            "team.created",
            f"{actor} created the team {team}.",
            target=team,
            members=after_members,
        )
    else:
        diff = changes(before, {"name": team.name, "description": team.description})
        if before_members != after_members:
            diff["members"] = {"old": before_members, "new": after_members}
        if diff:
            events.record(
                actor,
                "team.changed",
                f"{actor} changed the team {team}.",
                target=team,
                changes=diff,
            )
    return team


def delete_team(actor, team: Team) -> None:
    _require(actor, "users.manage")
    name = str(team)
    events.record(actor, "team.deleted", f"{actor} deleted the team {name}.", target=team)
    team.delete()


# Two-factor and access


def reset_mfa(actor, user: User) -> None:
    """Remove someone's authenticator app and recovery codes. They set it up again at sign-in."""
    _require(actor, "users.manage")
    from allauth.mfa.models import Authenticator

    removed = Authenticator.objects.filter(user=user).delete()[0]
    events.record(
        actor,
        "user.mfa_reset",
        f"{actor} reset two-factor for {user}.",
        target=user,
        removed=removed,
    )


def deactivate_user(actor, user: User, hand_over_to: User | None = None) -> None:
    """Deactivate a person. Their clients must be handed to someone who stays."""
    from apps.clients import services as client_services

    _require(actor, "users.manage")
    if actor.pk == user.pk:
        raise ValidationError("You cannot deactivate your own account.")
    if not user.is_active:
        return
    open_clients = client_services.clients_of(user).count()
    if open_clients and (hand_over_to is None or hand_over_to.pk == user.pk):
        raise ValidationError(
            f"{user} looks after {open_clients} client{'s' if open_clients != 1 else ''}. "
            "Choose who takes them over."
        )
    with transaction.atomic():
        user.is_active = False
        user.deactivated_at = timezone.now()
        try:
            user.save(update_fields=["is_active", "deactivated_at", "updated_at"])
        except LastOwnerError:
            user.is_active = True
            user.deactivated_at = None
            raise
        handed = client_services.hand_over_clients(actor, user, hand_over_to) if open_clients else 0
    note = f" Their {handed} clients went to {hand_over_to}." if handed else ""
    events.record(actor, "user.deactivated", f"{actor} deactivated {user}.{note}", target=user)


def reactivate_user(actor, user: User) -> None:
    _require(actor, "users.manage")
    if user.is_active:
        return
    user.is_active = True
    user.deactivated_at = None
    user.save(update_fields=["is_active", "deactivated_at", "updated_at"])
    events.record(actor, "user.reactivated", f"{actor} reactivated {user}.", target=user)


def update_profile(actor, form) -> User:
    """Save a profile form. Anyone may edit their own profile; users.manage may edit others."""
    user = form.instance
    if actor.pk != user.pk:
        _require(actor, "users.manage")
    fields = list(form.changed_data)
    before = {name: form.initial.get(name) for name in fields}
    user = form.save()
    after = {name: getattr(user, name) for name in fields}
    diff = changes(before, after)
    if diff:
        events.record(
            actor,
            "user.profile_changed",
            f"{actor} updated the profile of {user}.",
            target=user,
            changes=diff,
        )
    return user


def create_owner(*, email: str, name: str, password: str) -> User:
    role = Role.objects.get(slug=Role.OWNER)
    user = User.objects.create_user(email, password, name=name, role=role, kind=User.Kind.STAFF)
    events.record(
        None, "user.created", f"{user} was created as owner from the command line.", target=user
    )
    return user
