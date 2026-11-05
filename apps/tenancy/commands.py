"""Management commands that work on a practice's data.

Outside a web request the connection is on the public schema, which holds no
practice's data, so these commands take --practice SCHEMA. Commands that must
touch every practice (re-encrypting with a new key) run in each one by default.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context


def practice_schemas() -> list[str]:
    from apps.tenancy.models import Practice

    with schema_context(get_public_schema_name()):
        return list(
            Practice.objects.exclude(schema_name=get_public_schema_name())
            .order_by("schema_name")
            .values_list("schema_name", flat=True)
        )


class PracticeCommand(BaseCommand):
    every_practice_by_default = False
    default_practice = ""  # for development commands: the first demo practice

    def create_parser(self, prog_name, subcommand, **kwargs):
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.add_argument(
            "--practice",
            metavar="SCHEMA",
            help="The practice to work on, by its schema name (for example fpas).",
        )
        return parser

    def execute(self, *args, **options):
        schema = options.pop("practice", None)
        if schema:
            if schema not in practice_schemas():
                raise CommandError(f"There is no practice with the schema {schema!r}.")
            with schema_context(schema):
                return super().execute(*args, **options)
        if connection.schema_name != get_public_schema_name():
            return super().execute(*args, **options)
        if self.every_practice_by_default:
            for each in practice_schemas():
                self.stdout.write(f"Practice {each}:")
                with schema_context(each):
                    super().execute(*args, **options)
            return None
        if self.default_practice and self.default_practice in practice_schemas():
            with schema_context(self.default_practice):
                return super().execute(*args, **options)
        choices = ", ".join(practice_schemas()) or "none yet"
        raise CommandError(f"Say which practice with --practice SCHEMA ({choices}).")
