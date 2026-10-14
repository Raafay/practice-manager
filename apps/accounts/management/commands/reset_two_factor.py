"""Remove a staff member's authenticator app from the server console.

For when the only owner has lost their phone and their recovery codes, so nobody
can use Settings, Users. The person sets two-factor up again at their next sign-in.
The reset is recorded in the activity log.
"""

from allauth.mfa.models import Authenticator
from django.core.management.base import BaseCommand, CommandError

from apps import events
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Remove a staff member's authenticator app and recovery codes (logged)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, email, **options):
        user = User.objects.filter(email__iexact=email.strip(), kind=User.Kind.STAFF).first()
        if user is None:
            raise CommandError("No staff account has that email address.")
        removed = Authenticator.objects.filter(user=user).delete()[0]
        events.record(
            None,
            "user.mfa_reset",
            f"Two-factor was reset for {user} from the server console.",
            actor_label="Server console",
            target=user,
            removed=removed,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Two-factor reset for {user}. They set it up at next sign-in.")
        )
