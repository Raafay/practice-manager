import time
from importlib import import_module

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.demo import ensure_totp
from apps.accounts.models import User
from apps.accounts.signals import SESSION_SEEN, SESSION_STARTED


class Command(BaseCommand):
    help = "Development only: create a signed-in session for a user and print its id."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        if not settings.DEBUG:
            raise CommandError("dev_login works only when DEBUG is on.")
        user = User.objects.filter(email__iexact=email.strip()).first()
        if user is None or not user.is_active:
            raise CommandError("No active user has that email address.")
        if user.is_staff_kind:
            ensure_totp(user)  # two-factor counts as done
        session = import_module(settings.SESSION_ENGINE).SessionStore()
        now = time.time()
        session[SESSION_KEY] = str(user.pk)
        session[BACKEND_SESSION_KEY] = "allauth.account.auth_backends.AuthenticationBackend"
        session[HASH_SESSION_KEY] = user.get_session_auth_hash()
        session[SESSION_STARTED] = now
        session[SESSION_SEEN] = now
        session.create()
        self.stdout.write(session.session_key)
