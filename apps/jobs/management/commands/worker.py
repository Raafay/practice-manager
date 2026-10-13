import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from apps.jobs import services


class Command(BaseCommand):
    help = "Run background jobs when they are due. Loops for ever; checks once a minute."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Check once, then stop.")

    def handle(self, *args, once=False, **options):
        self.stdout.write("Worker started. Checking for due jobs once a minute.")
        while True:
            for run in services.run_due():
                self.stdout.write(f"{timezone.localtime():%d/%m/%Y %H:%M} {run.name}: {run.state}")
            if once:
                return
            close_old_connections()
            # Sleep to the start of the next minute.
            time.sleep(60 - time.time() % 60)
