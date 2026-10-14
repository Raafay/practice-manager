from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import demo as accounts_demo
from apps.accounts.models import User
from apps.aml import demo as aml_demo
from apps.clients import demo as clients_demo
from apps.comms import demo as comms_demo
from apps.companieshouse import demo as companieshouse_demo
from apps.core.models import PracticeSettings
from apps.finance import demo as finance_demo
from apps.imports import demo as imports_demo
from apps.onboarding import demo as onboarding_demo
from apps.pipeline import demo as pipeline_demo
from apps.portal import demo as portal_demo
from apps.services import demo as services_demo
from apps.tasks import demo as tasks_demo


class Command(BaseCommand):
    help = "Load made-up demo data. Safe to run twice. Refused unless demo data is allowed."

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.ALLOW_DEMO_DATA):
            raise CommandError(
                "Demo data is not allowed here. Set ALLOW_DEMO_DATA=true only on a test site."
            )
        with transaction.atomic():
            practice = PracticeSettings.objects.get_or_create(pk=1)[0]
            if practice.practice_name == PracticeSettings._meta.get_field("practice_name").default:
                practice.practice_name = "Hale & Castell Accountants (demo)"
                practice.address = "1 Example Street\nSampletown\nZZ1 1ZZ"
                practice.phone = "01632 960000"
                practice.email = "office@example.com"
                practice.vat_registered = True
                practice.save()
            people = accounts_demo.seed()
            staff = {u.email: u for u in User.objects.filter(email__in=[p[1] for p in people])}
            counts = clients_demo.seed(staff)
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
