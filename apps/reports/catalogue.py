"""The Stage 12 reports. See docs/specs/11-import-and-reports.md section 3.

Money appears only for people with `fees.view` (one row is one client's fee). A
practice-wide total needs `finance.owner` (CORRECTIONS 15). No report shows an
encrypted value or a document.
"""

from collections import defaultdict
from statistics import mean

from django import forms
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.comms.models import Channel, QueuedMessage
from apps.core.dates import add_months
from apps.events.models import ActivityEvent
from apps.pipeline.models import PipelineStage, ProspectDetails
from apps.portal.models import Request
from apps.services.models import ClientService, Service
from apps.tasks.models import Task, TaskCategory, TaskKind
from apps.timekeeping.models import TimeEntry

from .base import Column, Link, Report, ReportForm, Result, Section, date_field, hours, in_range
from .base import one_place as one_dp


def _people():
    return User.objects.staff().order_by("name")


def _client_link(client) -> Link | str:
    if client is None:
        return ""
    return Link(client.name, reverse("clients:detail", args=[client.pk]))


def _client_filter(queryset, text: str, prefix: str = "client__"):
    text = (text or "").strip()
    if not text:
        return queryset
    return queryset.filter(
        Q(**{f"{prefix}name__icontains": text}) | Q(**{f"{prefix}reference__iexact": text})
    )


# ---------------------------------------------------------------- tasks


class TaskFilter(ReportForm):
    STATES = [("open", "Open"), ("done", "Completed"), ("cancelled", "Cancelled"), ("all", "All")]

    state = forms.ChoiceField(choices=STATES, required=False, initial="open")
    owner = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Anyone"
    )
    client = forms.CharField(required=False, max_length=100)
    kind = forms.ChoiceField(choices=[("", "Any kind"), *TaskKind.choices], required=False)
    category = forms.ModelChoiceField(
        queryset=TaskCategory.objects.none(), required=False, empty_label="Any category"
    )
    due_from = date_field("Due from")
    due_to = date_field("Due to")
    done_from = date_field("Completed from")
    done_to = date_field("Completed to")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = _people()
        self.fields["category"].queryset = TaskCategory.objects.all()


class TasksReport(Report):
    key = "tasks"
    title = "Tasks"
    description = "Tasks by state, owner, client, kind and dates. Completed work in a date range."
    icon = "list-bullet"
    form_class = TaskFilter

    def build(self, data, user) -> Result:
        qs = Task.objects.select_related("client", "owner", "status", "category")
        state = data.get("state") or "open"
        if state == "open":
            qs = qs.open()
        elif state == "done":
            qs = qs.live().filter(status__is_done=True)
        elif state == "cancelled":
            qs = qs.filter(cancelled_at__isnull=False)
        if data.get("owner"):
            qs = qs.filter(owner=data["owner"])
        if data.get("kind"):
            qs = qs.filter(kind=data["kind"])
        if data.get("category"):
            qs = qs.filter(category=data["category"])
        qs = _client_filter(qs, data.get("client"))
        qs = in_range(qs, "due_date", data.get("due_from"), data.get("due_to"))
        if data.get("done_from"):
            qs = qs.filter(completed_at__date__gte=data["done_from"])
        if data.get("done_to"):
            qs = qs.filter(completed_at__date__lte=data["done_to"])
        qs = qs.order_by("due_date", "target_date", "title", "pk")
        rows = [
            [
                Link(t.title, reverse("tasks:detail", args=[t.pk])),
                _client_link(t.client),
                t.get_kind_display(),
                t.category.name if t.category else "",
                t.status.name,
                t.owner.name if t.owner else "Unassigned",
                t.target_date,
                t.due_date,
                timezone.localtime(t.completed_at).date() if t.completed_at else None,
            ]
            for t in qs
        ]
        today = timezone.localdate()
        overdue = sum(1 for r in rows if r[7] and r[7] < today and r[8] is None)
        return Result(
            columns=[
                Column("Task"),
                Column("Client"),
                Column("Kind"),
                Column("Category"),
                Column("Status"),
                Column("Owner"),
                Column("Target date"),
                Column("Due date"),
                Column("Completed"),
            ],
            rows=rows,
            figures=[("Tasks", len(rows)), ("Past their due date", overdue)],
        )


# ---------------------------------------------------------------- services


class ServiceFilter(ReportForm):
    STATES = [("open", "Active or proposed"), *ClientService.State.choices, ("all", "All")]

    service = forms.ModelChoiceField(
        queryset=Service.objects.none(), required=False, empty_label="Any service"
    )
    state = forms.ChoiceField(choices=STATES, required=False, initial="open")
    status = forms.ChoiceField(
        label="Client status", choices=[("", "Any status"), *Client.Status.choices], required=False
    )
    client = forms.CharField(required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.all()


class ServicesReport(Report):
    key = "services"
    title = "Services"
    description = "Which clients take which services. Fees show only if you may see them."
    icon = "rectangle-stack"
    form_class = ServiceFilter

    def build(self, data, user) -> Result:
        qs = ClientService.objects.select_related("client", "service").filter(
            client__archived_at__isnull=True
        )
        state = data.get("state") or "open"
        if state == "open":
            qs = qs.exclude(state=ClientService.State.ENDED)
        elif state != "all":
            qs = qs.filter(state=state)
        if data.get("service"):
            qs = qs.filter(service=data["service"])
        if data.get("status"):
            qs = qs.filter(client__status=data["status"])
        qs = _client_filter(qs, data.get("client")).order_by("client__name", "service__position")
        fees = user.can("fees.view")
        columns = [
            Column("Client"),
            Column("Reference"),
            Column("Service"),
            Column("State"),
            Column("Starts"),
            Column("Ends"),
        ]
        if fees:
            columns += [Column("Fee", True), Column("Frequency"), Column("Monthly", True)]
        rows = []
        for cs in qs:
            row = [
                _client_link(cs.client),
                cs.client.reference,
                cs.service.name,
                cs.get_state_display(),
                cs.starts_on,
                cs.ends_on,
            ]
            if fees:
                row += [cs.fee_amount, cs.get_fee_frequency_display(), cs.monthly_equivalent]
            rows.append(row)
        figures = [("Lines", len(rows)), ("Clients", len({r[1] for r in rows}))]
        if fees and user.can("finance.owner"):
            total = sum((r[8] or 0) for r in rows)
            figures.append(("Monthly total", f"£{total:,.2f}"))
        counts = defaultdict(int)
        for cs in qs:
            counts[cs.service.name] += 1
        section = Section(
            "Clients per service",
            [Column("Service"), Column("Clients", True)],
            [[name, n] for name, n in sorted(counts.items())],
        )
        return Result(columns=columns, rows=rows, figures=figures, sections=[section])


# ---------------------------------------------------------------- time


class TimeFilter(ReportForm):
    GROUPS = [
        ("client", "Client"),
        ("person", "Person"),
        ("service", "Service"),
        ("month", "Month"),
    ]

    group = forms.ChoiceField(label="Hours by", choices=GROUPS, required=False, initial="client")
    start = date_field("From")
    end = date_field("To")
    person = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Everyone"
    )
    client = forms.CharField(required=False, max_length=100)
    billable = forms.ChoiceField(
        choices=[("", "Billable or not"), ("yes", "Billable only"), ("no", "Not billable only")],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["person"].queryset = _people()


class TimeReport(Report):
    key = "time"
    title = "Time"
    description = "Hours by client, person, service and month."
    icon = "clock"
    form_class = TimeFilter

    GROUP_FIELDS = {
        "client": ("client__name", "Client"),
        "person": ("user__name", "Person"),
        "service": ("service__name", "Service"),
        "month": ("month", "Month"),
    }

    def build(self, data, user) -> Result:
        # Without a start date: this month and the two before it.
        start = data.get("start") or add_months(timezone.localdate().replace(day=1), -2)
        qs = in_range(TimeEntry.objects.all(), "date", start, data.get("end"))
        if data.get("person"):
            qs = qs.filter(user=data["person"])
        qs = _client_filter(qs, data.get("client"))
        if data.get("billable") == "yes":
            qs = qs.filter(billable=True)
        elif data.get("billable") == "no":
            qs = qs.filter(billable=False)
        group = data.get("group") or "client"
        name, label = self.GROUP_FIELDS[group]
        if group == "month":
            qs = qs.annotate(month=TruncMonth("date"))
        grouped = (
            qs.values(name)
            .annotate(
                total=Sum("minutes"),
                billable_total=Sum("minutes", filter=Q(billable=True)),
                entries=Count("pk"),
            )
            .order_by(name)
        )
        rows = []
        for g in grouped:
            key = g[name]
            if group == "month":
                key = key.strftime("%m/%Y") if key else ""
            rows.append(
                [
                    key or {"client": "No client", "service": "No service"}.get(group, ""),
                    hours(g["total"]),
                    hours(g["billable_total"]),
                    g["entries"],
                ]
            )
        total = sum((r[1] for r in rows), start=hours(0))
        return Result(
            columns=[
                Column(label),
                Column("Hours", True),
                Column("Billable hours", True),
                Column("Entries", True),
            ],
            rows=rows,
            figures=[("From", start), ("Hours", total)],
        )


# ---------------------------------------------------------------- requests


OPEN_REQUEST_STATES = (Request.State.NEW, Request.State.IN_PROGRESS)
FIRST_ACTION_VERBS = [
    "request.client_set",
    "request.converted",
    "request.linked",
    "request.answered",
    "request.closed",
    "request.spam",
]


class RequestFilter(ReportForm):
    group = forms.ChoiceField(
        label="Group by",
        choices=[("channel", "Channel"), ("client", "Client")],
        required=False,
        initial="channel",
    )
    start = date_field("Received from")
    end = date_field("Received to")
    channel = forms.ChoiceField(
        choices=[("", "Any channel"), *Request.Channel.choices], required=False
    )
    client = forms.CharField(required=False, max_length=100)


class RequestsReport(Report):
    key = "requests"
    title = "Requests"
    description = "Volume, time to first action and time to close, by client and channel."
    icon = "inbox"
    form_class = RequestFilter

    def build(self, data, user) -> Result:
        qs = Request.objects.select_related("client")
        if data.get("start"):
            qs = qs.filter(received_at__date__gte=data["start"])
        if data.get("end"):
            qs = qs.filter(received_at__date__lte=data["end"])
        if data.get("channel"):
            qs = qs.filter(channel=data["channel"])
        qs = _client_filter(qs, data.get("client"))
        requests = list(qs)
        firsts = dict(
            ActivityEvent.objects.filter(
                target_type__model="request",
                target_type__app_label="portal",
                target_id__in=[str(r.pk) for r in requests],
                verb__in=FIRST_ACTION_VERBS,
            )
            .values("target_id")
            .annotate(first=Min("created_at"))
            .values_list("target_id", "first")
        )
        group = data.get("group") or "channel"
        buckets: dict[str, list[Request]] = defaultdict(list)
        for r in requests:
            if group == "client":
                buckets[r.client.name if r.client else "No client yet"].append(r)
            else:
                buckets[r.get_channel_display()].append(r)
        rows = []
        for name in sorted(buckets):
            items = buckets[name]
            real = [r for r in items if r.state != Request.State.SPAM]
            first = [
                (firsts[str(r.pk)] - r.received_at).total_seconds() / 3600
                for r in real
                if str(r.pk) in firsts
            ]
            closed = [
                (r.closed_at - r.received_at).total_seconds() / 3600
                for r in real
                if r.closed_at and r.state == Request.State.CLOSED
            ]
            rows.append(
                [
                    name,
                    len(real),
                    sum(
                        1 for r in real if r.state in (Request.State.NEW, Request.State.IN_PROGRESS)
                    ),
                    len(closed),
                    len(items) - len(real),
                    one_dp(mean(first)) if first else None,
                    one_dp(mean(closed)) if closed else None,
                ]
            )
        return Result(
            columns=[
                Column("Client" if group == "client" else "Channel"),
                Column("Requests", True),
                Column("Still open", True),
                Column("Closed", True),
                Column("Spam", True),
                Column("Hours to first action (average)", True),
                Column("Hours to close (average)", True),
            ],
            rows=rows,
            figures=[("Requests", sum(r[1] for r in rows))],
        )


# ---------------------------------------------------------------- pipeline


class PipelineFilter(ReportForm):
    start = date_field("Enquiry from")
    end = date_field("Enquiry to")
    owner = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Anyone"
    )
    source = forms.ChoiceField(choices=[("", "Any source"), *Client.Source.choices], required=False)
    outcome = forms.ChoiceField(
        choices=[("", "Any outcome"), ("open", "Open"), ("won", "Won"), ("lost", "Lost")],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = _people()


def _outcome(stage: PipelineStage) -> str:
    return "Won" if stage.is_won else "Lost" if stage.is_lost else "Open"


class PipelineReport(Report):
    key = "pipeline"
    title = "Pipeline"
    description = "Prospects by stage, source and outcome, with won and lost reasons."
    icon = "funnel"
    form_class = PipelineFilter

    def build(self, data, user) -> Result:
        qs = ProspectDetails.objects.select_related("client", "stage", "owner")
        qs = in_range(qs, "enquiry_date", data.get("start"), data.get("end"))
        if data.get("owner"):
            qs = qs.filter(owner=data["owner"])
        if data.get("source"):
            qs = qs.filter(client__source=data["source"])
        outcome = data.get("outcome")
        if outcome == "won":
            qs = qs.filter(stage__is_won=True)
        elif outcome == "lost":
            qs = qs.filter(stage__is_lost=True)
        elif outcome == "open":
            qs = qs.filter(stage__is_won=False, stage__is_lost=False)
        items = list(qs.order_by("-enquiry_date", "client__name"))
        rows = [
            [
                _client_link(p.client),
                p.stage.name,
                p.client.get_source_display() or "Not recorded",
                p.owner.name if p.owner else "",
                p.enquiry_date,
                _outcome(p.stage),
                p.won_on or p.lost_on,
                p.get_lost_reason_display() if p.stage.is_lost else "",
            ]
            for p in items
        ]
        by_stage = defaultdict(int)
        by_source = defaultdict(lambda: [0, 0, 0])
        reasons = defaultdict(int)
        for p in items:
            by_stage[(p.stage.position, p.stage.name)] += 1
            counts = by_source[p.client.get_source_display() or "Not recorded"]
            counts[0] += 1
            counts[1] += p.stage.is_won
            counts[2] += p.stage.is_lost
            if p.stage.is_lost:
                reasons[p.get_lost_reason_display() or "No reason given"] += 1
        won = sum(1 for p in items if p.stage.is_won)
        lost = sum(1 for p in items if p.stage.is_lost)
        sections = [
            Section(
                "By stage",
                [Column("Stage"), Column("Prospects", True)],
                [[name, n] for (_pos, name), n in sorted(by_stage.items())],
            ),
            Section(
                "By source",
                [
                    Column("Source"),
                    Column("Prospects", True),
                    Column("Won", True),
                    Column("Lost", True),
                ],
                [[name, *c] for name, c in sorted(by_source.items())],
            ),
            Section(
                "Lost reasons",
                [Column("Reason"), Column("Prospects", True)],
                [[name, n] for name, n in sorted(reasons.items(), key=lambda x: -x[1])],
            ),
        ]
        return Result(
            columns=[
                Column("Prospect"),
                Column("Stage"),
                Column("Source"),
                Column("Owner"),
                Column("Enquiry"),
                Column("Outcome"),
                Column("Won or lost on"),
                Column("Lost reason"),
            ],
            rows=rows,
            figures=[("Prospects", len(items)), ("Won", won), ("Lost", lost)],
            sections=sections,
        )


# ---------------------------------------------------------------- communications


class MessageFilter(ReportForm):
    start = date_field("Created from")
    end = date_field("Created to")
    channel = forms.ChoiceField(choices=[("", "Any channel"), *Channel.choices], required=False)


class CommunicationsReport(Report):
    key = "communications"
    title = "Communications"
    description = "Messages sent, failed and bounced, by template."
    icon = "envelope"
    form_class = MessageFilter

    def build(self, data, user) -> Result:
        S = QueuedMessage.State
        qs = QueuedMessage.objects.all()
        if data.get("start"):
            qs = qs.filter(created_at__date__gte=data["start"])
        if data.get("end"):
            qs = qs.filter(created_at__date__lte=data["end"])
        if data.get("channel"):
            qs = qs.filter(channel=data["channel"])
        grouped = (
            qs.values("template__name")
            .annotate(
                sent=Count("pk", filter=Q(state=S.SENT)),
                delivered=Count("pk", filter=Q(delivery_state=QueuedMessage.Delivery.DELIVERED)),
                bounced=Count("pk", filter=Q(delivery_state=QueuedMessage.Delivery.BOUNCED)),
                failed=Count("pk", filter=Q(state=S.FAILED)),
                waiting=Count("pk", filter=Q(state__in=[S.DRAFT, S.NEEDS_APPROVAL, S.APPROVED])),
                cancelled=Count("pk", filter=Q(state=S.CANCELLED)),
            )
            .order_by("template__name")
        )
        rows = [
            [
                g["template__name"] or "Written by hand",
                g["sent"],
                g["delivered"],
                g["bounced"],
                g["failed"],
                g["waiting"],
                g["cancelled"],
            ]
            for g in grouped
        ]
        return Result(
            columns=[
                Column("Template"),
                Column("Sent", True),
                Column("Delivered", True),
                Column("Bounced", True),
                Column("Failed", True),
                Column("Waiting", True),
                Column("Cancelled", True),
            ],
            rows=rows,
            figures=[
                ("Sent", sum(r[1] for r in rows)),
                ("Failed", sum(r[4] for r in rows)),
                ("Bounced", sum(r[3] for r in rows)),
            ],
        )


REPORTS: dict[str, Report] = {
    r.key: r
    for r in (
        TasksReport(),
        ServicesReport(),
        TimeReport(),
        RequestsReport(),
        PipelineReport(),
        CommunicationsReport(),
    )
}
