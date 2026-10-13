from django.core.management.base import BaseCommand, CommandError

from apps.companieshouse import api, services


class Command(BaseCommand):
    help = "Make one live profile call to Companies House and print the filing dates."

    def add_arguments(self, parser):
        parser.add_argument("number", help="Company number, such as 09999901 or SC001234.")

    def handle(self, *args, number, **options):
        self.stdout.write(f"API key: {'present' if api.key_present() else 'not set'}")
        try:
            profile = api.get_client().profile(number)
        except api.CompaniesHouseError as error:
            raise CommandError(error.public_message) from None
        fields = services.profile_fields(profile)

        def show(value):
            return value.strftime("%d/%m/%Y") if value else "none"

        lines = [
            ("Name", profile.get("company_name", "")),
            ("Number", profile.get("company_number", "")),
            ("Status", services.status_label(profile.get("company_status", ""))),
            ("Type", services.status_label(profile.get("type", ""))),
            ("Incorporated", show(fields["incorporated_on"])),
            (
                "Accounting reference date",
                f"{fields['accounting_ref_day']:02d}/{fields['accounting_ref_month']:02d}"
                if fields["accounting_ref_day"] and fields["accounting_ref_month"]
                else "none",
            ),
            ("Last accounts made up to", show(fields["last_accounts_made_up_to"])),
            ("Next accounts made up to", show(fields["next_accounts_made_up_to"])),
            ("Next accounts due", show(fields["next_accounts_due"])),
            ("Last statement made up to", show(fields["last_statement_made_up_to"])),
            ("Next statement made up to", show(fields["next_statement_made_up_to"])),
            ("Next statement due", show(fields["next_statement_due"])),
        ]
        for label, value in lines:
            self.stdout.write(f"{label + ':':<28} {value}")
