import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.services import backup_is_recent, move_into_schema, newest_backup


class Command(BaseCommand):
    help = (
        "Move the original practice's tables from the public schema into its own schema, "
        "in one transaction, after checking a backup was taken in the last hour. "
        "Stop the website and the worker first."
    )

    def add_arguments(self, parser):
        parser.add_argument("schema", help="The practice's new schema, for example fpas")
        parser.add_argument("--domain", required=True, help="Its address, e.g. fpas.example.com")
        parser.add_argument("--name", default="", help="Its name (default: from Practice settings)")
        parser.add_argument(
            "--backup",
            help="The backup file just taken (default: the newest db_*.dump in BACKUP_DIR)",
        )
        parser.add_argument("--from", dest="source", default="public", help="Default: public")
        parser.add_argument("--noinput", action="store_true", help="Do not ask to confirm")

    def handle(self, *args, schema, domain, name, backup, source, noinput, **options):
        if backup:
            path = Path(backup)
        elif os.environ.get("BACKUP_DIR"):
            path = newest_backup(Path(os.environ["BACKUP_DIR"])) or Path(os.environ["BACKUP_DIR"])
        else:
            raise CommandError("Take a backup first and name it with --backup FILE.")
        problem = backup_is_recent(path)
        if problem:
            raise CommandError(f"{problem} Take a fresh backup first (docs/BACKUPS.md).")
        if not noinput:
            answer = input(
                f"Move every practice table from {source} into {schema} ({domain})? "
                "The website and worker must be stopped. Type yes: "
            )
            if answer.strip().lower() != "yes":
                raise CommandError("Nothing was changed.")
        try:
            result = move_into_schema(
                schema_name=schema, domain=domain.strip().lower(), name=name, source=source
            )
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        total = sum(result.counts.values())
        self.stdout.write(
            self.style.SUCCESS(
                f"Moved {len(result.counts)} tables ({total} rows, every count the same) "
                f"into {schema}. {result.practice.name} answers at {domain}."
            )
        )
        if result.files_note:
            self.stdout.write(result.files_note)
        else:
            self.stdout.write(f"Moved {result.files_moved} uploaded file(s) into {schema}/.")
