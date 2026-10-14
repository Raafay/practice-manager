"""Background work for imports: "Fetch from Companies House" for the clients a run created."""

from datetime import time

from django.utils import timezone

from apps.companieshouse import api
from apps.companieshouse import services as ch_services
from apps.jobs.registry import Daily, register

from .models import ImportedRecord, ImportRun
from .services import companies_to_fetch

# Stop if this many companies in a row cannot be reached: the service is down.
GIVE_UP_AFTER = 3


def fetch_run(run: ImportRun, ch=None) -> dict:
    """Sync each company in turn, saving progress after each one, so the page can show it.

    A run stopped half way picks up where it left off.
    """
    ch = ch or api.get_client()
    ImportRun.objects.filter(pk=run.pk).update(fetch_state=ImportRun.FetchState.RUNNING)
    clients = list(companies_to_fetch(run))
    start = run.fetch_done + run.fetch_failed
    in_a_row = 0
    for client in clients[start:]:
        try:
            ch_services.sync_client(client, actor=run.created_by, ch=ch)
        except api.AuthFailed:
            raise
        except api.CompaniesHouseError:
            run.fetch_failed += 1
            in_a_row += 1
            ImportRun.objects.filter(pk=run.pk).update(fetch_failed=run.fetch_failed)
            if in_a_row >= GIVE_UP_AFTER:
                # Left as running: the next run carries on from here.
                raise
            continue
        in_a_row = 0
        run.fetch_done += 1
        # The fetch is the system's own change: undo still treats the client as untouched.
        ImportedRecord.objects.filter(
            run=run, model=ImportedRecord.Model.CLIENT, object_id=client.pk
        ).update(stamp=timezone.now())
        ImportRun.objects.filter(pk=run.pk).update(fetch_done=run.fetch_done)
    ImportRun.objects.filter(pk=run.pk).update(fetch_state=ImportRun.FetchState.DONE)
    return {"fetched": run.fetch_done, "failed": run.fetch_failed}


@register(
    "import_fetch",
    "Fetch imported companies",
    Daily(time(4, 30)),
    description="Fills in imported clients from Companies House when the owner asks. "
    "Normally started from the import page.",
)
def import_fetch(job_run):
    counts = {"runs": 0, "fetched": 0, "failed": 0}
    waiting = ImportRun.objects.filter(
        fetch_state__in=[ImportRun.FetchState.WAITING, ImportRun.FetchState.RUNNING]
    ).order_by("pk")
    for run in waiting:
        result = fetch_run(run)
        counts["runs"] += 1
        counts["fetched"] += result["fetched"]
        counts["failed"] += result["failed"]
    return counts
