from django.core.management.base import BaseCommand, CommandError

from apps.jobs import registry, services


class Command(BaseCommand):
    help = "Run one background job now."

    def add_arguments(self, parser):
        parser.add_argument("name", help="The job's name. Leave out to list them.", nargs="?")

    def handle(self, *args, name=None, **options):
        if not name:
            for job in registry.all_jobs():
                self.stdout.write(f"{job.name:<20} {job.label} ({job.schedule.describe()})")
            return
        try:
            registry.get(name)
        except KeyError as error:
            raise CommandError(str(error)) from None
        run = services.run_job(name)
        if run is None:
            raise CommandError(f"{name} is already running.")
        detail = ", ".join(f"{k} {v}" for k, v in run.counts.items())
        self.stdout.write(f"{name}: {run.get_state_display()}. {run.message} {detail}".strip())
        if run.state == run.State.FAILED:
            raise CommandError(run.message)
