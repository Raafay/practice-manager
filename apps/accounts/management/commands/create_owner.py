import getpass
import os

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.services import create_owner


class Command(BaseCommand):
    help = "Create the first owner. They set up two-factor when they first sign in."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument(
            "--password-from-env",
            metavar="VARIABLE",
            help="Read the password from this environment variable instead of asking.",
        )

    def handle(self, *args, email, name, password_from_env=None, **options):
        email = email.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("Someone already has an account with this email address.")
        if password_from_env:
            password = os.environ.get(password_from_env, "")
            if not password:
                raise CommandError(f"The environment variable {password_from_env} is empty.")
        else:
            password = getpass.getpass("Password (at least 12 characters): ")
            if password != getpass.getpass("Password again: "):
                raise CommandError("The two passwords do not match.")
        try:
            password_validation.validate_password(password, User(email=email, name=name))
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        user = create_owner(email=email, name=name, password=password)
        self.stdout.write(
            self.style.SUCCESS(f"Owner {user.email} created. Sign in to set up two-factor.")
        )
