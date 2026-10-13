"""Record sign-in, sign-out, failed sign-in, lockout and two-factor changes."""

import time

from allauth.account import signals as account_signals
from allauth.mfa import signals as mfa_signals
from axes.signals import user_locked_out
from django.contrib.auth import signals as auth_signals
from django.dispatch import receiver

from apps import events

SESSION_STARTED = "pm_started_at"
SESSION_SEEN = "pm_seen_at"


def _attempted_email(credentials) -> str:
    credentials = credentials or {}
    return str(credentials.get("email") or credentials.get("username") or "")[:200]


@receiver(auth_signals.user_logged_in)
def on_signed_in(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        now = time.time()
        request.session[SESSION_STARTED] = now
        request.session[SESSION_SEEN] = now
    events.record(user, "auth.signed_in", f"{user} signed in.", target=user, request=request)


@receiver(auth_signals.user_logged_out)
def on_signed_out(sender, request, user, **kwargs):
    if user is None:
        return
    events.record(user, "auth.signed_out", f"{user} signed out.", target=user, request=request)


@receiver(auth_signals.user_login_failed)
def on_sign_in_failed(sender, credentials, request=None, **kwargs):
    email = _attempted_email(credentials)
    events.record(
        None,
        "auth.sign_in_failed",
        "A sign-in failed.",
        actor_label=email or "Unknown",
        request=request,
    )


@receiver(user_locked_out)
def on_locked_out(sender, request, username, ip_address, **kwargs):
    events.record(
        None,
        "auth.locked_out",
        "An account was locked for 15 minutes after five failed sign-ins.",
        actor_label=str(username or "Unknown")[:200],
        request=request,
    )


@receiver(account_signals.password_changed)
def on_password_changed(sender, request, user, **kwargs):
    events.record(
        user,
        "auth.password_changed",
        f"{user} changed their password.",
        target=user,
        request=request,
    )


@receiver(account_signals.password_reset)
def on_password_reset(sender, request, user, **kwargs):
    events.record(
        user, "auth.password_reset", f"{user} reset their password.", target=user, request=request
    )


@receiver(mfa_signals.authenticator_added)
def on_authenticator_added(sender, request, user, authenticator, **kwargs):
    events.record(
        user,
        "auth.mfa_added",
        f"{user} set up {authenticator.get_type_display().lower()}.",
        target=user,
        request=request,
    )


@receiver(mfa_signals.authenticator_removed)
def on_authenticator_removed(sender, request, user, authenticator, **kwargs):
    events.record(
        user,
        "auth.mfa_removed",
        f"{user} removed {authenticator.get_type_display().lower()}.",
        target=user,
        request=request,
    )


@receiver(mfa_signals.authenticator_reset)
def on_authenticator_reset(sender, request, user, authenticator, **kwargs):
    events.record(
        user,
        "auth.recovery_codes_reset",
        f"{user} made new recovery codes.",
        target=user,
        request=request,
    )
