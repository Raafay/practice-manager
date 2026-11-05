from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context

from apps.accounts import demo as accounts_demo
from apps.accounts.models import User
from apps.aml import demo as aml_demo
from apps.clients import demo as clients_demo
from apps.comms import demo as comms_demo
from apps.companieshouse import demo as companieshouse_demo
from apps.core.models import PracticeSettings
from apps.creditsafe import demo as creditsafe_demo
from apps.finance import demo as finance_demo
from apps.imports import demo as imports_demo
from apps.onboarding import demo as onboarding_demo
from apps.pipeline import demo as pipeline_demo
from apps.portal import demo as portal_demo
from apps.services import demo as services_demo
from apps.tasks import demo as tasks_demo

# Two made-up practices, so the separation between practices can be seen. The first
# has the full demo data; the second has only the same staff accounts and no clients.
# Browsers send any *.localhost address to this computer.
DEMO_PRACTICES = [
    {
        "name": "Hale & Castell Accountants (demo)",
        "schema_name": "demo",
        "domains": ["localhost", "127.0.0.1"],
        "full": True,
    },
    {
        "name": "Brook & Lantern Accounts (demo)",
        "schema_name": "demo_second",
        "domains": ["second.localhost"],
        "full": False,
    },
]


def ensure_demo_practice(spec):
    from apps.tenancy.models import Domain, Practice
    from apps.tenancy.services import create_practice

    with schema_context(get_public_schema_name()):
        practice = Practice.objects.filter(schema_name=spec["schema_name"]).first()
        if practice is None:
            practice = create_practice(
                name=spec["name"], schema_name=spec["schema_name"], domain=spec["domains"][0]
            )
        for domain in spec["domains"][1:]:
            Domain.objects.get_or_create(
                domain=domain, defaults={"tenant": practice, "is_primary": False}
            )
    return practice


class Command(BaseCommand):
    help = (
        "Load made-up demo data. Safe to run twice. Refused unless demo data is allowed. "
        "Run on its own it makes two demo practices (http://localhost:8000 and "
        "http://second.localhost:8000); run inside a practice it fills only that one."
    )

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.ALLOW_DEMO_DATA):
            raise CommandError(
                "Demo data is not allowed here. Set ALLOW_DEMO_DATA=true only on a test site."
            )
        if connection.schema_name != get_public_schema_name():
            return self.seed(DEMO_PRACTICES[0]["name"], full=True)
        for spec in DEMO_PRACTICES:
            practice = ensure_demo_practice(spec)
            with schema_context(practice.schema_name):
                from apps.core.siteurl import absolute

                self.stdout.write(self.style.SUCCESS(f"{spec['name']}: {absolute('/')}"))
                self.seed(spec["name"], full=spec["full"])
            self.stdout.write("")

    def seed(self, practice_name, *, full):
        with transaction.atomic():
            practice = PracticeSettings.objects.get_or_create(pk=1)[0]
            if not practice.address and practice.practice_name in (
                PracticeSettings._meta.get_field("practice_name").default,
                practice_name,
            ):
                practice.practice_name = practice_name
                practice.address = "1 Example Street\nSampletown\nZZ1 1ZZ"
                practice.phone = "01632 960000"
                practice.email = "office@example.com"
                practice.vat_registered = True
                practice.save()
            people = accounts_demo.seed()
            if not full:
                self.stdout.write("  Staff accounts only, no clients.")
                self.sign_in_help(people)
                return
            staff = {u.email: u for u in User.objects.filter(email__in=[p[1] for p in people])}
            counts = clients_demo.seed(staff)
            clients_demo.seed_retention()
            # Straight after the clients, so later seeds treat imported clients the same each run.
            counts.update(imports_demo.seed())
            counts.update(companieshouse_demo.seed())
            counts.update(services_demo.seed())
            counts.update(tasks_demo.seed())
            counts.update(comms_demo.seed())
            counts.update(aml_demo.seed())
            counts.update(onboarding_demo.seed())
            counts.update(pipeline_demo.seed())
            counts.update(portal_demo.seed())
            counts.update(finance_demo.seed())
            counts.update(creditsafe_demo.seed())

        self.stdout.write(self.style.SUCCESS("Demo data loaded. Everything here is made up."))
        self.stdout.write(
            f"  {counts['clients']} clients, {counts['contacts']} people, "
            f"{counts['documents']} documents, "
            f"{counts['snapshots']} new Companies House snapshots, "
            f"{counts['client_services']} new client services, "
            f"{counts['deadlines']} new deadlines, "
            f"{counts['tasks']} tasks in all ({counts['advisory_tasks']} new fractional), "
            f"{counts['messages']} queued messages, "
            f"{counts['assessments']} new risk assessments, "
            f"{counts['onboarding_clients']} new onboarding clients, "
            f"{counts['prospects']} new prospects ({counts['proposals']} proposals, "
            f"{counts['won']} won, {counts['lost']} lost)."
        )
        self.stdout.write(
            f"  {counts['portal_users']} portal users, {counts['portal_items']} things to do, "
            f"{counts['requests']} requests."
        )
        self.stdout.write(
            f"  {counts['time_entries']} new time entries, {counts['xero_invoices']} made-up "
            f"Xero invoices, {counts['targets']} new monthly targets."
        )
        self.stdout.write("")
        self.sign_in_help(people)

    def sign_in_help(self, people):
        self.stdout.write("Sign in at /login/ with any of these:")
        for name, email, role in people:
            self.stdout.write(f"  {role:<8} {name:<15} {email}")
        self.stdout.write(f"  Password for all: {accounts_demo.DEMO_PASSWORD}")
        bypass = getattr(settings, "MFA_TOTP_INSECURE_BYPASS_CODE", None)
        if bypass:
            self.stdout.write(f"  Two-factor code (development only): {bypass}")
        else:
            self.stdout.write(
                "  Two-factor: no bypass code is set. Use `manage.py dev_login` in development."
            )
