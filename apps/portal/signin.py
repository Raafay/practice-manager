"""Portal sign-in by emailed code (spec 01 section 4).

The person enters their email. If it belongs to a portal user a six-digit code is
emailed: ten minutes, five tries. The page says the same whether or not the email is
known. Staff accounts are never offered a code. Sign-in emails go straight out
(CORRECTIONS 17), not through the approval queue.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.core.mail import EmailMultiAlternatives
from django.db.models import F
from django.utils import timezone

from apps import events
from apps.accounts.models import User
from apps.core import ratelimit
from apps.core.models import PracticeSettings

from .models import PortalLoginCode

CODE_MINUTES = 10
MAX_TRIES = 5
SESSION_EMAIL = "portal_login_email"
BACKEND = "allauth.account.auth_backends.AuthenticationBackend"


def hash_code(user_id: int, code: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{user_id}:{code}".encode()).hexdigest()


def portal_user_for(email: str) -> User | None:
    user = User.objects.filter(email__iexact=(email or "").strip()).first()
    if user is None or not user.is_portal or not user.is_active:
        return None
    return user


def send_code(request, email: str) -> None:
    """Email a code if the address belongs to a portal user. Always returns quietly."""
    email = (email or "").strip().lower()[:254]
    ip = ratelimit.client_ip(request)
    if not ratelimit.hit(f"portal-code-ip:{ip}", 10, 3600) or not ratelimit.hit(
        f"portal-code-email:{email}", 5, 3600
    ):
        return
    user = portal_user_for(email)
    if user is None:
        known = User.objects.filter(email__iexact=email).exists()
        events.record(
            None,
            "portal.code_refused",
            "A portal code was asked for by an address that is not a portal user"
            + (" (a staff account)." if known else "."),
            actor_label=email or "Unknown",
            request=request,
        )
        return
    from .models import portal_clients

    if not portal_clients(user).exists():
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    PortalLoginCode.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    PortalLoginCode.objects.create(
        user=user,
        code_hash=hash_code(user.pk, code),
        expires_at=timezone.now() + timedelta(minutes=CODE_MINUTES),
    )
    practice = PracticeSettings.load()
    from apps.comms.services import sending_address

    message = EmailMultiAlternatives(
        subject=f"Your sign-in code for {practice.practice_name}",
        body=(
            f"Your sign-in code is {code}.\n\n"
            f"It works for {CODE_MINUTES} minutes. If you did not ask for it, "
            "ignore this email; nobody can sign in without it.\n\n"
            f"{practice.practice_name}"
        ),
        from_email=sending_address(practice),
        to=[user.email],
    )
    message.send()
    events.record(
        user,
        "portal.code_sent",
        f"A sign-in code was emailed to {user.email}.",
        target=user,
        request=request,
    )


def check_code(request, email: str, code: str) -> User | None:
    """Sign the person in if the code is right. Wrong, expired and unknown all look the same."""
    email = (email or "").strip().lower()[:254]
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    ip = ratelimit.client_ip(request)
    if not ratelimit.hit(f"portal-verify-ip:{ip}", 30, 3600):
        return None
    user = portal_user_for(email)
    if user is None:
        return None
    entry = (
        PortalLoginCode.objects.filter(user=user, used_at__isnull=True)
        .order_by("-created_at")
        .first()
    )
    if entry is None or entry.expires_at <= timezone.now() or entry.attempts >= MAX_TRIES:
        return None
    # Count the try in the database in one step, so requests sent at the same moment
    # cannot all slip under the limit.
    counted = PortalLoginCode.objects.filter(
        pk=entry.pk, used_at__isnull=True, attempts__lt=MAX_TRIES
    ).update(attempts=F("attempts") + 1, updated_at=timezone.now())
    if not counted:
        return None
    if not hmac.compare_digest(entry.code_hash, hash_code(user.pk, code)):
        events.record(
            user,
            "portal.sign_in_failed",
            f"A wrong portal code was entered for {user.email}.",
            target=user,
            request=request,
        )
        return None
    # Used once: only the request that marks it used goes on to sign in.
    if not PortalLoginCode.objects.filter(pk=entry.pk, used_at__isnull=True).update(
        used_at=timezone.now(), updated_at=timezone.now()
    ):
        return None
    request.session.cycle_key()
    login(request, user, backend=BACKEND)
    return user
