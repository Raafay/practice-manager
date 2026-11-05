from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from apps.accounts.services import invite_first_owner
from apps.core.siteurl import absolute
from apps.tenancy.services import create_practice


class Command(BaseCommand):
    help = (
        "Create an empty practice with its own schema and address, and invite its owner. "
        "Takes about ten seconds: every table is made in the new schema."
    )

    def add_arguments(self, parser):
        parser.add_argument("name", help='The practice\'s name, for example "Example Accountants"')
        parser.add_argument("schema", help="Its schema and file folder name, for example example")
        parser.add_argument("domain", help="Its address, for example example.pm.example.com")
        parser.add_argument("owner_email", help="The owner, who gets an invitation by email")
        parser.add_argument("--owner-name", help="The owner's name (default: from the email)")

    def handle(self, *args, name, schema, domain, owner_email, owner_name=None, **options):
        domain = domain.strip().lower()
        owner_email = owner_email.strip().lower()
        if "@" not in owner_email:
            raise CommandError("The owner's email address is not valid.")
        try:
            practice = create_practice(name=name.strip(), schema_name=schema, domain=domain)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        with schema_context(practice.schema_name):
            invitation, link = invite_first_owner(
                email=owner_email, name=owner_name or owner_email.split("@")[0]
            )
            address = absolute("/")
        self.stdout.write(self.style.SUCCESS(f"Practice {practice.name} created at {address}"))
        self.stdout.write(
            f"An invitation was emailed to {invitation.email}. It lasts 72 hours. "
            f"If the email does not arrive, send them this link: {link}"
        )
