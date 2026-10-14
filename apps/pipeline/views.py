"""Staff side of the pipeline: the Prospects page, new prospects, sales details and meetings."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.clients.models import Client
from apps.clients.views_base import done, get_client, render_form
from apps.core.permissions import StaffRequiredMixin

from . import services
from .forms import MeetingForm, MoveForm, NewProspectForm, ProspectFilterForm, SalesForm
from .models import PipelineStage, ProspectDetails

SORTS = {
    "name": lambda c: c.client.name.lower(),
    "stage": lambda c: c.details.stage.position,
    "fee": lambda c: c.fee,
    "next": lambda c: (c.details.next_action_date is None, c.details.next_action_date),
    "days": lambda c: c.days_in_stage,
    "owner": lambda c: c.details.owner.name.lower() if c.details.owner else "~",
}


def is_fetch(request) -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


class ProspectsView(StaffRequiredMixin, View):
    """The board and the list: two views of the same prospects with the same filters."""

    def get(self, request):
        form = ProspectFilterForm(request.GET)
        filters = form.filters()
        cards = services.board_rows(filters)
        view = "list" if request.GET.get("view") == "list" else "board"
        sort = request.GET.get("sort", "")
        descending = sort.startswith("-")
        sort_key = sort.lstrip("-")
        rows = [c for c in cards if c.details.stage.is_open] if view == "list" else cards
        if view == "list":
            rows = sorted(rows, key=SORTS.get(sort_key, SORTS["name"]), reverse=descending)
        query = request.GET.copy()
        query.pop("view", None)
        query.pop("sort", None)
        context = {
            "form": form,
            "view": view,
            "columns": services.columns(cards),
            "rows": rows,
            "figures": services.header_figures(cards),
            "can_fees": request.user.can("fees.view"),
            "can_owner_figures": request.user.can("finance.owner"),
            "sort": sort_key,
            "descending": descending,
            "keep_query": query.urlencode(),
            "any_prospects": bool(cards),
            "lost_stage": PipelineStage.objects.filter(is_lost=True).first(),
            "won_stage": PipelineStage.objects.filter(is_won=True).first(),
        }
        return render(request, "pipeline/prospects.html", context)


class ProspectNewView(StaffRequiredMixin, View):
    def _render(self, request, form, status=200):
        return render(request, "pipeline/prospect_new.html", {"form": form}, status=status)

    def get(self, request):
        return self._render(request, NewProspectForm(can_fees=request.user.can("fees.view")))

    def post(self, request):
        form = NewProspectForm(request.POST, can_fees=request.user.can("fees.view"))
        if not form.is_valid():
            return self._render(request, form, 422)
        data = form.cleaned_data
        client = services.create_prospect(
            request.user,
            name=data["name"],
            client_type=data["client_type"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data["phone"],
            source=data["source"],
            referred_by_client=data["referred_by_client"],
            referred_by_text=data["referred_by_text"],
            expected_fee=data.get("expected_fee"),
            next_action=data["next_action"],
            next_action_date=data["next_action_date"],
            notes=data["notes"],
            owner=data["owner"],
        )
        return done(
            request, reverse("clients:detail", args=[client.pk]), f"{client.name} was added."
        )


class ProspectMoveView(StaffRequiredMixin, View):
    """Change a prospect's stage. Dragging to Lost or Won opens a dialog first."""

    def _stage(self, value) -> PipelineStage:
        if not str(value).isdigit():
            raise Http404
        return get_object_or_404(PipelineStage, pk=int(value))

    def _next(self, request) -> str:
        """Where to go afterwards: the client page if the move came from there."""
        target = request.POST.get("next", "")
        if target.startswith("/clients/") and not target.startswith("//"):
            return target
        return reverse("pipeline:prospects")

    def _dialog(self, request, client, stage, form=None, status=200):
        return render(
            request,
            "pipeline/_move_dialog.html",
            {"client": client, "stage": stage, "form": form or MoveForm()},
            status=status,
        )

    def get(self, request, pk):
        client = get_client(pk)
        stage = self._stage(request.GET.get("to", ""))
        services.ensure_details(client, request.user)
        return self._dialog(request, client, stage)

    def post(self, request, pk):
        client = get_client(pk)
        stage = self._stage(request.POST.get("to", ""))
        if client.status not in (Client.Status.PROSPECT, Client.Status.LOST):
            raise Http404
        reason = note = ""
        if stage.is_lost:
            form = MoveForm(request.POST)
            if not form.is_valid():
                if is_fetch(request):
                    return HttpResponse("Say why this prospect was lost.", status=422)
                return self._dialog(request, client, stage, form, 422)
            reason, note = form.cleaned_data["lost_reason"], form.cleaned_data["lost_note"]
        elif stage.is_won and request.POST.get("confirm") != "1":
            return HttpResponse("Confirm that this prospect has accepted.", status=422)
        try:
            details = services.move_stage(
                request.user, client, stage, lost_reason=reason, lost_note=note
            )
        except ValidationError as error:
            if is_fetch(request):
                return HttpResponse(" ".join(error.messages), status=422)
            messages.error(request, " ".join(error.messages))
            return done(request, self._next(request))
        if is_fetch(request):
            card = services.card_for(details)
            return render(
                request,
                "pipeline/_card.html",
                {"card": card, "can_fees": request.user.can("fees.view")},
            )
        text = (
            f"{client.name} is won and is now onboarding."
            if details.stage.is_won
            else f"{client.name} moved to {details.stage.name}."
        )
        return done(request, self._next(request), text)


class SalesEditView(StaffRequiredMixin, View):
    """Edit the Sales panel: owner, source, referrer, expected start, next action, fees."""

    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Sales details: {client.name}",
            form=form,
            action=reverse("pipeline:sales_edit", args=[client.pk]),
            status=status,
            back=reverse("clients:detail", args=[client.pk]),
        )

    def get(self, request, pk):
        client = get_client(pk)
        details = services.ensure_details(client, request.user)
        form = SalesForm(instance=details, client=client, can_fees=request.user.can("fees.view"))
        return self._render(request, client, form)

    def post(self, request, pk):
        client = get_client(pk)
        details = services.ensure_details(client, request.user)
        form = SalesForm(
            request.POST, instance=details, client=client, can_fees=request.user.can("fees.view")
        )
        if not form.is_valid():
            return self._render(request, client, form, 422)
        fields = {
            k: v
            for k, v in form.cleaned_data.items()
            if k not in ("source", "referred_by_client", "referred_by_text")
        }
        # The model form has already set the instance; compare against the stored row.
        stored = ProspectDetails.objects.get(pk=details.pk)
        services.save_sales(request.user, stored, **fields)
        services.save_referral(
            request.user,
            client,
            source=form.cleaned_data["source"],
            referred_by_client=form.cleaned_data["referred_by_client"],
            referred_by_text=form.cleaned_data["referred_by_text"],
        )
        return done(request, reverse("clients:detail", args=[client.pk]), "Sales details saved.")


class MeetingAddView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Log a meeting: {client.name}",
            form=form,
            action=reverse("pipeline:meeting_add", args=[client.pk]),
            submit="Save meeting",
            status=status,
            back=reverse("clients:detail", args=[client.pk]),
        )

    def get(self, request, pk):
        client = get_client(pk)
        now = timezone.localtime()
        form = MeetingForm(
            initial={"on_date": now.date(), "at_time": now.time().replace(second=0, microsecond=0)}
        )
        return self._render(request, client, form)

    def post(self, request, pk):
        client = get_client(pk)
        form = MeetingForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        services.log_meeting(
            request.user,
            client,
            held_at=form.held_at(),
            kind=data["kind"],
            place=data["place"],
            staff=data["staff"],
            people=data["people"],
            notes=data["notes"],
            outcome=data["outcome"],
            follow_up=data["follow_up"],
            follow_up_date=data["follow_up_date"],
        )
        return done(request, reverse("clients:detail", args=[client.pk]), "Meeting logged.")


def sales_context(client: Client, user) -> dict:
    """What the Sales and Meetings panels on the Info tab need. Empty for an ordinary client."""
    if client.status in (Client.Status.PROSPECT, Client.Status.LOST):
        services.ensure_details(client)
    details = ProspectDetails.objects.filter(client=client).select_related("stage", "owner").first()
    if details is None:
        return {}
    can_fees = user.can("fees.view")
    return {
        "sales": {
            "details": details,
            "fee": services.expected_monthly(client, details) if can_fees else None,
            "from_services": client.client_services.filter(state="proposed").exists(),
            "quiet": services.is_quiet(details),
            "quiet_reason": services.quiet_reason(details) if services.is_quiet(details) else "",
            "can_fees": can_fees,
            "overdue": bool(
                details.next_action_date and details.next_action_date < timezone.localdate()
            ),
            "stages": PipelineStage.objects.filter(is_open=True),
            "won_stage": PipelineStage.objects.filter(is_won=True).first(),
            "lost_stage": PipelineStage.objects.filter(is_lost=True).first(),
            "meetings": list(client.meetings.select_related("created_by")[:6]),
            "is_open": details.stage.is_open and client.status == Client.Status.PROSPECT,
        }
    }
