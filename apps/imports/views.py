"""Settings, Import: the four-step wizard, past runs, undo, Companies House and the helper.

Every view needs `data.import`. Running an import or an undo asks for the password again.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.core.csvexport import csv_response
from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin
from apps.jobs import services as jobs

from . import helper, services
from .forms import MappingForm, UploadForm
from .models import ImportRun, Kind, SavedMatching

PREVIEW_ROWS = 10
STEPS = ["Upload", "Match columns", "Check", "Import"]


class ImportAccess(CapabilityRequiredMixin):
    required_rights = ("data.import",)


def _run(pk) -> ImportRun:
    return get_object_or_404(ImportRun, pk=pk)


def _errors(error: ValidationError) -> str:
    return " ".join(error.messages)


class ImportIndexView(ImportAccess, View):
    def get(self, request, form=None, status=200):
        return render(
            request,
            "imports/index.html",
            {
                "form": form or UploadForm(),
                "page": paginate(request, ImportRun.objects.select_related("created_by"), 20),
                "matchings": SavedMatching.objects.all(),
                "helper_count": helper.open_recent().count(),
            },
            status=status,
        )

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.get(request, form, 422)
        upload = form.cleaned_data["file"]
        try:
            run = services.start_run(
                request.user, form.cleaned_data["kind"], upload.name, upload.read()
            )
        except ValidationError as error:
            form.add_error("file", _errors(error))
            return self.get(request, form, 422)
        return redirect("imports:match", run.pk)


class MatchView(ImportAccess, View):
    """Step 2: a drop-down for each column, suggested from the heading or a saved matching."""

    def get(self, request, pk, form=None, status=200):
        run = _run(pk)
        if run.state != ImportRun.State.UPLOADED:
            return redirect("imports:run", run.pk)
        form = form or MappingForm(run=run)
        rows = [r for r in services.rows_of(run) if any(c.strip() for c in r)][:PREVIEW_ROWS]
        # Tax references and codes are not shown back on screen.
        hidden = services.sensitive_columns(run)
        rows = [
            [services.LEFT_OUT if i in hidden and c.strip() else c for i, c in enumerate(r)]
            for r in rows
        ]
        return render(
            request,
            "imports/match.html",
            {
                "run": run,
                "form": form,
                "columns": [
                    (field, [r[i] for r in rows]) for i, field in enumerate(form.column_fields())
                ],
                "matchings": SavedMatching.objects.filter(kind=run.kind),
                "preview": rows,
                "step": 2,
                "wizard_steps": STEPS,
            },
            status=status,
        )

    def post(self, request, pk):
        run = _run(pk)
        if request.POST.get("use_matching"):
            matching = get_object_or_404(
                SavedMatching, pk=request.POST["use_matching"], kind=run.kind
            )
            services.apply_matching(run, matching)
            messages.success(request, f"Columns matched using “{matching.name}”.")
            return redirect("imports:match", run.pk)
        form = MappingForm(request.POST, run=run)
        if not form.is_valid():
            return self.get(request, pk, form, 422)
        try:
            services.set_mapping(
                request.user,
                run,
                form.mapping(),
                overwrite=form.cleaned_data["overwrite"],
                save_as=form.cleaned_data["save_as"],
            )
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.get(request, pk, form, 422)
        return redirect("imports:check", run.pk)


class CheckView(ImportAccess, View):
    """Step 3 shows what would happen; its button is step 4."""

    require_reauth = True

    def get(self, request, pk):
        run = _run(pk)
        if run.state != ImportRun.State.UPLOADED:
            return redirect("imports:run", run.pk)
        result = services.check(run)
        return render(
            request,
            "imports/check.html",
            {
                "run": run,
                "result": result,
                "counts": result.counts,
                "warned": [r for r in result.rows if r.ok and r.warnings],
                "sample": [r for r in result.rows if r.ok][:20],
                "step": 3,
                "wizard_steps": STEPS,
            },
        )

    def post(self, request, pk):
        run = _run(pk)
        try:
            run = services.run_import(request.user, run)
        except ValidationError as error:
            messages.error(request, _errors(error))
            return redirect("imports:run", run.pk)
        messages.success(request, "Import finished.")
        return redirect("imports:run", run.pk)


class RunView(ImportAccess, View):
    def get(self, request, pk):
        run = _run(pk)
        if run.state == ImportRun.State.UPLOADED:
            return redirect("imports:match", run.pk)
        return render(
            request,
            "imports/run.html",
            {
                "run": run,
                "failures": services.failure_rows(run)[:50],
                "failure_count": run.counts.get("failed", 0),
                "records": run.records.all()[:50],
                "record_count": run.records.count(),
                "can_fetch": run.kind == Kind.CLIENTS
                and run.state == ImportRun.State.DONE
                and services.companies_to_fetch(run).exists(),
                "worker_seen": jobs.worker_last_seen(),
                "helper_count": helper.open_recent().count() if run.kind == Kind.SERVICES else 0,
            },
        )


class FailuresView(ImportAccess, View):
    """The rows that were not imported, with the reason, as CSV. Tax references are left out."""

    # A download of client data: the password is asked for again, as for exports.
    require_reauth = True
    reauth_allow_get = False

    def get(self, request, pk):
        run = _run(pk)
        rows = services.failure_rows(run)
        response, writer = csv_response(f"not-imported-{run.pk}.csv")
        writer.writerow(["Row", "Problem", *run.headers])
        for item in rows:
            writer.writerow([item["row"], item["problem"], *item["values"]])
        events.record(
            request.user,
            "export.run",
            f"{request.user} downloaded the {len(rows)} rows not imported from {run.file_name}.",
            target=run,
            rows=len(rows),
            list="import failures",
        )
        return response


class UndoView(ImportAccess, View):
    require_reauth = True

    def post(self, request, pk):
        run = _run(pk)
        try:
            run = services.undo(request.user, run)
        except ValidationError as error:
            messages.error(request, _errors(error))
        else:
            removed, kept = run.counts.get("removed", 0), run.counts.get("kept", 0)
            messages.success(
                request,
                f"Import undone: {removed} removed"
                + (f", {kept} kept because they had changed." if kept else "."),
            )
        return redirect("imports:run", run.pk)


class FetchView(ImportAccess, View):
    def post(self, request, pk):
        run = _run(pk)
        try:
            services.request_fetch(request.user, run)
        except ValidationError as error:
            messages.error(request, _errors(error))
        else:
            messages.success(request, "Fetching from Companies House. Progress shows below.")
        return redirect("imports:run", run.pk)


class ProgressView(ImportAccess, View):
    """The progress panel, polled by the run page while a fetch is under way."""

    def get(self, request, pk):
        run = _run(pk)
        return render(
            request,
            "imports/_fetch_progress.html",
            {"run": run, "worker_seen": jobs.worker_last_seen()},
        )


class MatchingDeleteView(ImportAccess, View):
    def post(self, request, pk):
        matching = get_object_or_404(SavedMatching, pk=pk)
        name = matching.name
        matching.delete()
        events.record(request.user, "import.matching_deleted", f"{request.user} deleted “{name}”.")
        messages.success(request, f"Saved matching “{name}” deleted.")
        return redirect("imports:index")


class HelperView(ImportAccess, View):
    """Mark deadlines that were dealt with in the old system as already done."""

    def get(self, request):
        groups = helper.groups()
        return render(
            request,
            "imports/helper.html",
            {
                "groups": groups,
                "total": sum(len(items) for _title, items in groups),
                "days": helper.WITHIN_DAYS,
                "today": timezone.localdate(),
                "index_url": reverse("imports:index"),
            },
        )

    def post(self, request):
        ids = request.POST.getlist("ids")
        if not ids:
            messages.error(request, "Tick the deadlines that were already dealt with.")
            return redirect("imports:helper")
        count = helper.mark_already_done(
            request.user, ids, complete_tasks=bool(request.POST.get("complete_tasks"))
        )
        messages.success(
            request, f"{count} deadline{'s' if count != 1 else ''} marked as already done."
        )
        return redirect(reverse("imports:helper"))
