"""Factories for people. Names are invented; emails use example.com."""

import time

import factory
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    yield_hotp_counters_from_time,
)

from apps.accounts.models import Role, Team, User

PASSWORD = "a-long-test-password"


class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Team
        django_get_or_create = ["name"]

    name = factory.Sequence(lambda n: f"Team {n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    class Params:
        role_slug = Role.STAFF

    email = factory.Sequence(lambda n: f"person{n}@example.com")
    name = factory.Sequence(lambda n: f"Test Person {n}")
    kind = User.Kind.STAFF
    role = factory.LazyAttribute(lambda o: Role.objects.get(slug=o.role_slug))

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or PASSWORD)
        if create:
            obj.save(update_fields=["password"])


def owner(**kwargs) -> User:
    return UserFactory(role_slug=Role.OWNER, **kwargs)


def manager(**kwargs) -> User:
    return UserFactory(role_slug=Role.MANAGER, **kwargs)


def staff(**kwargs) -> User:
    return UserFactory(role_slug=Role.STAFF, **kwargs)


def portal_user(**kwargs) -> User:
    kwargs.setdefault("role", None)
    return UserFactory(kind=User.Kind.PORTAL, **kwargs)


def add_totp(user: User) -> str:
    """Give the user an authenticator app. Returns its secret."""
    secret = generate_totp_secret()
    Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).delete()
    TOTP.activate(user, secret)
    return secret


def totp_code(secret: str, offset: int = 0) -> str:
    """The authenticator code for now, or for a time step before or after (with tolerance)."""
    counters = list(yield_hotp_counters_from_time())
    current = counters[len(counters) // 2]
    return format_hotp_value(hotp_value(secret, current + offset))


def sign_in(client, user: User, *, mfa: bool = True, recent_password: bool = True):
    """Sign a test client in as user. With mfa, the user has an authenticator app."""
    if mfa and user.is_staff_kind:
        add_totp(user)
    client.force_login(user)
    if recent_password:
        session = client.session
        session["account_authentication_methods"] = [{"method": "password", "at": time.time()}]
        session.save()
    return client
