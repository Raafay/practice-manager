"""The sales side: stages, quiet prospects, meetings and the header figures (spec 05)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client, Note
from apps.core.money import to_pounds
from apps.services.fees import monthly_equivalent
from apps.services.models import ClientService

from .models import Meeting, PipelineSettings, PipelineStage, Proposal, ProspectDetails

WON_LOST_WINDOW_DAYS = 30
STATS_DAYS = 365


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


# ---------------------------------------------------------------- stages


def first_stage() -> PipelineStage:
    stage = (
        PipelineStage.objects.filter(is_open=True, is_on_hold=False).order_by("position").first()
    )
    return stage or PipelineStage.objects.order_by("position").first()


def stage_of_kind(*, won: bool = False, lost: bool = False) -> PipelineStage:
    field = "is_won" if won else "is_lost"
    stage = PipelineStage.objects.filter(**{field: True}).order_by("position").first()
    if stage is None:
        raise ValidationError(
            "There is no Won or Lost stage. Add one under Settings, Pipeline stages."
        )
    return stage


def ensure_details(client: Client, actor=None) -> ProspectDetails:
    """The sales row for a client, made on first use. Safe to call twice."""
    details = ProspectDetails.objects.filter(client=client).select_related("stage").first()
    if details is not None:
        return details
    now = timezone.now()
    stage = first_stage()
    if client.status == Client.Status.LOST:
        stage = stage_of_kind(lost=True)
    elif client.status in (Client.Status.ONBOARDING, Client.Status.ACTIVE, Client.Status.PAUSED):
        stage = stage_of_kind(won=True)
    return ProspectDetails.objects.create(
        client=client,
        stage=stage,
        stage_changed_at=now,
        owner=client.manager,
        enquiry_date=timezone.localdate(),
        last_activity_at=now,
    )


def backfill_details() -> int:
    """Give every prospect without a sales row one. Prospects come from imports and status moves."""
    missing = Client.objects.filter(status=Client.Status.PROSPECT, prospect__isnull=True)
    count = 0
    for client in missing:
        ensure_details(client)
        count += 1
    return count


def touch(client: Client, when: datetime | None = None) -> None:
    """Something happened with this prospect: restart the quiet clock."""
    ProspectDetails.objects.filter(client=client).update(
        last_activity_at=when or timezone.now(), updated_at=timezone.now()
    )


# ---------------------------------------------------------------- fees


def proposed_services(client: Client):
    return client.client_services.filter(state=ClientService.State.PROPOSED).select_related(
        "service"
    )


def expected_monthly(client: Client, details: ProspectDetails | None = None) -> Decimal:
    """The proposed services' monthly total, or the hand-entered figure when none are ticked."""
    rows = list(proposed_services(client))
    if rows:
        total = Decimal("0.00")
        for row in rows:
            total += monthly_equivalent(row.fee_amount, row.fee_frequency) or Decimal("0.00")
        return total
    details = details or ProspectDetails.objects.filter(client=client).first()
    if details is not None and details.expected_fee is not None:
        return to_pounds(details.expected_fee)
    return Decimal("0.00")


def weighted(fee: Decimal, chance: int) -> Decimal:
    return to_pounds(Decimal(fee) * Decimal(chance) / Decimal(100))


# ---------------------------------------------------------------- quiet


def quiet_days() -> int:
    return PipelineSettings.load().quiet_days


def last_activity(details: ProspectDetails) -> datetime | None:
    """The latest of the stored time and anything recorded elsewhere for the client."""
    from apps.comms.models import QueuedMessage
    from apps.tasks.models import Task, TaskKind

    client = details.client
    candidates = [details.last_activity_at, details.created_at]
    note = client.notes.aggregate(m=Max("created_at"))["m"]
    sent = QueuedMessage.objects.filter(client=client, state="sent").aggregate(m=Max("sent_at"))[
        "m"
    ]
    done = Task.objects.filter(
        client=client, kind=TaskKind.SALES, completed_at__isnull=False
    ).aggregate(m=Max("completed_at"))["m"]
    meeting = client.meetings.aggregate(m=Max("created_at"))["m"]
    proposal = client.proposals.aggregate(a=Max("sent_at"), b=Max("viewed_at"))
    candidates += [note, sent, done, meeting, proposal["a"], proposal["b"]]
    candidates = [c for c in candidates if c is not None]
    return max(candidates) if candidates else None


def is_quiet(details: ProspectDetails, today: date | None = None, days: int | None = None) -> bool:
    """In an open stage other than On hold, and the next action date has passed or 14 days idle."""
    stage = details.stage
    if not stage.is_open or stage.is_on_hold:
        return False
    if details.client.status != Client.Status.PROSPECT:
        return False
    today = today or timezone.localdate()
    days = quiet_days() if days is None else days
    if details.next_action_date is not None and details.next_action_date < today:
        return True
    activity = last_activity(details)
    if activity is None:
        return False
    cutoff = datetime.combine(today, time.min, tzinfo=timezone.get_current_timezone()) - timedelta(
        days=days - 1
    )
    return activity < cutoff


def quiet_reason(details: ProspectDetails, today: date | None = None) -> str:
    today = today or timezone.localdate()
    if details.next_action_date is not None and details.next_action_date < today:
        return f"Next action was due {details.next_action_date:%d/%m/%Y}"
    activity = last_activity(details)
    return f"Nothing since {timezone.localtime(activity):%d/%m/%Y}" if activity else "No activity"


def open_prospects():
    return ProspectDetails.objects.filter(
        client__status=Client.Status.PROSPECT, client__archived_at__isnull=True, stage__is_open=True
    ).select_related("client", "stage", "owner")


def quiet_prospects(user=None, today: date | None = None) -> list[ProspectDetails]:
    rows = [d for d in open_prospects() if is_quiet(d, today)]
    if user is not None and not user.can("finance.owner"):
        rows = [d for d in rows if d.owner_id == user.pk]
    rows.sort(key=lambda d: d.next_action_date or date.max)
    return rows


# ---------------------------------------------------------------- moves


@transaction.atomic
def move_stage(
    actor, client: Client, stage: PipelineStage, *, lost_reason: str = "", lost_note: str = ""
) -> ProspectDetails:
    """Put a prospect in a stage. Lost needs a reason; Won starts onboarding."""
    details = ensure_details(client, actor)
    old = details.stage
    if old.pk == stage.pk:
        return details
    if old.is_won:
        raise ValidationError("This prospect is a client now, so it cannot go back on the board.")
    today = timezone.localdate()
    if stage.is_lost:
        if lost_reason not in ProspectDetails.LostReason.values:
            raise ValidationError("Say why this prospect was lost.")
        details.lost_reason = lost_reason
        details.lost_note = lost_note.strip()[:300]
        details.lost_on = today
        details.won_on = None
    elif stage.is_won:
        details.won_on = today
        details.lost_on = None
        details.lost_reason = details.lost_note = ""
    else:
        details.lost_on = None
        details.lost_reason = details.lost_note = ""
    details.stage = stage
    details.stage_changed_at = timezone.now()
    details.last_activity_at = timezone.now()
    details.save()
    if stage.is_lost and client.status == Client.Status.PROSPECT:
        client_services.set_status(actor, client, Client.Status.LOST, reason=details.lost_note)
    elif stage.is_won and client.status == Client.Status.PROSPECT:
        client_services.set_status(actor, client, Client.Status.ONBOARDING)
    elif old.is_lost and not stage.is_lost and client.status == Client.Status.LOST:
        client_services.set_status(actor, client, Client.Status.PROSPECT)
    events.record(
        actor,
        "prospect.stage_changed",
        f"{who(actor)} moved {client.name} from {old.name} to {stage.name}."
        + (f" Reason: {details.get_lost_reason_display()}." if stage.is_lost else ""),
        client=client,
        target=details,
        old=old.name,
        new=stage.name,
    )
    if stage.is_won:
        notify_won(actor, client, details)
    return details


def notify_won(actor, client: Client, details: ProspectDetails) -> None:
    from apps.onboarding.services import notify_staff

    notify_staff(
        client,
        f"{client.name} is won and is now onboarding.",
        f"/clients/{client.pk}/onboarding/",
        details.owner,
    )


def sync_from_status(client: Client, old: str, new: str, actor=None) -> None:
    """The client page changed the status by hand: keep the sales stage in line."""
    details = ProspectDetails.objects.filter(client=client).select_related("stage").first()
    if details is None:
        return
    stage = details.stage
    if new == Client.Status.LOST and not stage.is_lost:
        details.stage = stage_of_kind(lost=True)
        details.lost_on = timezone.localdate()
        details.lost_reason = details.lost_reason or ProspectDetails.LostReason.OTHER
        details.lost_note = details.lost_note or "Marked lost on the client page."
    elif new == Client.Status.ONBOARDING and not stage.is_won:
        details.stage = stage_of_kind(won=True)
        details.won_on = timezone.localdate()
    elif new == Client.Status.PROSPECT and (stage.is_lost or stage.is_won):
        details.stage = first_stage()
        details.lost_on = details.won_on = None
        details.lost_reason = details.lost_note = ""
    else:
        return
    details.stage_changed_at = timezone.now()
    details.last_activity_at = timezone.now()
    details.save()


# ---------------------------------------------------------------- sales details


@transaction.atomic
def save_sales(actor, details: ProspectDetails, **fields) -> ProspectDetails:
    changed = {}
    for key, value in fields.items():
        if getattr(details, key) != value:
            changed[key] = [str(getattr(details, key) or ""), str(value or "")]
            setattr(details, key, value)
    if not changed:
        return details
    if "next_action" in changed or "next_action_date" in changed:
        details.last_activity_at = timezone.now()
    details.save()
    events.record(
        actor,
        "prospect.updated",
        f"{who(actor)} changed the sales details for {details.client.name}.",
        client=details.client,
        target=details,
        changes=changed,
    )
    return details


def save_referral(
    actor, client: Client, *, source: str, referred_by_client, referred_by_text: str
) -> Client:
    """Source and referrer are kept on the client, where the Internal panel shows them too."""
    changed = {}
    for key, value in (
        ("source", source),
        ("referred_by_client", referred_by_client),
        ("referred_by_text", referred_by_text),
    ):
        if getattr(client, key) != value and (getattr(client, key) or value):
            changed[key] = [str(getattr(client, key) or ""), str(value or "")]
            setattr(client, key, value)
    if changed:
        client.save()
        events.record(
            actor,
            "client.updated",
            f"{who(actor)} changed how {client.name} found the practice.",
            client=client,
            target=client,
            changes=changed,
        )
        client_services.client_updated.send(sender=Client, client=client, actor=actor)
    return client


@transaction.atomic
def log_meeting(
    actor,
    client: Client,
    *,
    held_at: datetime,
    kind: str,
    place: str = "",
    staff=(),
    people: str = "",
    notes: str = "",
    outcome: str = "",
    follow_up: str = "",
    follow_up_date: date | None = None,
) -> Meeting:
    meeting = Meeting.objects.create(
        client=client,
        held_at=held_at,
        kind=kind,
        place=place,
        people=people,
        notes=notes,
        outcome=outcome,
        follow_up=follow_up.strip(),
        follow_up_date=follow_up_date,
        created_by=actor,
    )
    meeting.staff.set(staff)
    details = ProspectDetails.objects.filter(client=client).select_related("stage").first()
    if meeting.follow_up:
        meeting.follow_up_task = _follow_up_task(actor, client, meeting, details)
        meeting.save(update_fields=["follow_up_task", "updated_at"])
    if details is not None:
        details.last_activity_at = timezone.now()
        update = ["last_activity_at", "updated_at"]
        if meeting.follow_up:
            details.next_action = meeting.follow_up[:250]
            details.next_action_date = follow_up_date
            update += ["next_action", "next_action_date"]
        # A first meeting moves an enquiry on; later stages are left alone.
        booked = PipelineStage.objects.filter(key__in=("enquiry", "meeting_booked")).values_list(
            "pk", flat=True
        )
        held = PipelineStage.objects.filter(key="meeting_held").first()
        if held is not None and details.stage_id in set(booked) and held_at <= timezone.now():
            details.stage = held
            details.stage_changed_at = timezone.now()
            update += ["stage", "stage_changed_at"]
        details.save(update_fields=update)
    events.record(
        actor,
        "meeting.logged",
        f"{who(actor)} logged a {meeting.get_kind_display().lower()} meeting with "
        f"{client.name} on {timezone.localtime(held_at):%d/%m/%Y}.",
        client=client,
        target=meeting,
    )
    return meeting


def _follow_up_task(actor, client, meeting, details):
    from apps.tasks.models import TaskCategory, TaskKind
    from apps.tasks.services import create_task

    owner = details.owner if details is not None and details.owner else actor
    return create_task(
        actor,
        title=f"Follow up: {meeting.follow_up}"[:250],
        client=client,
        kind=TaskKind.SALES,
        category=TaskCategory.objects.filter(name="Sales").first(),
        owner=owner,
        target_date=meeting.follow_up_date,
        description=f"<p>From the meeting on {timezone.localtime(meeting.held_at):%d/%m/%Y}.</p>",
        notify=owner is not None and owner != actor,
    )


# ---------------------------------------------------------------- new prospect


@transaction.atomic
def create_prospect(
    actor,
    *,
    name: str,
    client_type: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    phone: str = "",
    source: str = "",
    referred_by_client=None,
    referred_by_text: str = "",
    expected_fee=None,
    next_action: str = "",
    next_action_date=None,
    notes: str = "",
    owner=None,
) -> Client:
    contact = None
    if first_name or email or phone:
        existing = (
            client_services.find_matching_contacts(
                email=email, first_name=first_name, last_name=last_name
            ).first()
            if email
            else None
        )
        contact = existing or client_services.create_contact(
            actor,
            first_name=first_name or name,
            last_name=last_name,
            email=email,
            phone=phone,
        )
    client = client_services.create_client(
        actor,
        name=name,
        client_type=client_type,
        manager=owner,
        status=Client.Status.PROSPECT,
        contact=contact,
        source=source,
        referred_by_client=referred_by_client,
        referred_by_text=referred_by_text,
    )
    details = ensure_details(client, actor)
    details.owner = owner or actor
    details.expected_fee = expected_fee
    details.next_action = next_action
    details.next_action_date = next_action_date
    details.save()
    if notes.strip():
        Note.objects.create(client=client, text=notes.strip(), author=actor)
    return client


# ---------------------------------------------------------------- board and figures


@dataclass
class Card:
    details: ProspectDetails
    client: Client
    fee: Decimal
    main_contact: object
    days_in_stage: int
    quiet: bool
    overdue: bool


@dataclass
class Column:
    stage: PipelineStage
    cards: list
    total: Decimal

    @property
    def count(self) -> int:
        return len(self.cards)


def _card(details: ProspectDetails, today: date, days: int) -> Card:
    client = details.client
    changed = details.stage_changed_at or details.created_at
    return Card(
        details=details,
        client=client,
        fee=expected_monthly(client, details),
        main_contact=client.main_contact,
        days_in_stage=max((today - timezone.localtime(changed).date()).days, 0),
        quiet=is_quiet(details, today, days),
        overdue=bool(details.next_action_date and details.next_action_date < today),
    )


def card_for(details: ProspectDetails, today: date | None = None) -> Card:
    return _card(details, today or timezone.localdate(), quiet_days())


def board_rows(filters: dict, today: date | None = None) -> list[Card]:
    """Every prospect on the board: open ones, plus Won and Lost from the last 30 days."""
    backfill_details()
    today = today or timezone.localdate()
    window = today - timedelta(days=WON_LOST_WINDOW_DAYS)
    queryset = ProspectDetails.objects.filter(client__archived_at__isnull=True).select_related(
        "client", "stage", "owner"
    )
    queryset = queryset.filter(
        Q(stage__is_open=True, client__status=Client.Status.PROSPECT)
        | Q(stage__is_won=True, won_on__gte=window)
        | Q(stage__is_lost=True, lost_on__gte=window)
    )
    if filters.get("owner") == "none":
        queryset = queryset.filter(owner__isnull=True)
    elif filters.get("owner"):
        queryset = queryset.filter(owner_id=filters["owner"])
    if filters.get("stage"):
        queryset = queryset.filter(stage_id=filters["stage"])
    if filters.get("source"):
        queryset = queryset.filter(client__source=filters["source"])
    days = quiet_days()
    cards = [_card(d, today, days) for d in queryset.order_by("client__name")]
    if filters.get("quiet"):
        cards = [c for c in cards if c.quiet]
    return cards


def columns(cards: list[Card]) -> list[Column]:
    result = []
    for stage in PipelineStage.objects.order_by("position"):
        mine = [c for c in cards if c.details.stage_id == stage.pk]
        mine.sort(key=lambda c: (c.details.next_action_date or date.max, c.client.name))
        result.append(Column(stage, mine, sum((c.fee for c in mine), Decimal("0.00"))))
    return result


def header_figures(cards_open: list[Card], today: date | None = None) -> dict:
    """Open value, weighted value, proposals waiting, win rate and days to win (12 months)."""
    today = today or timezone.localdate()
    since = today - timedelta(days=STATS_DAYS)
    open_cards = [c for c in cards_open if c.details.stage.is_open]
    open_value = sum((c.fee for c in open_cards), Decimal("0.00"))
    weighted_value = sum(
        (weighted(c.fee, c.details.stage.chance) for c in open_cards), Decimal("0.00")
    )
    waiting = Proposal.objects.filter(
        state__in=(Proposal.State.SENT, Proposal.State.VIEWED),
        client__status=Client.Status.PROSPECT,
    ).count()
    won = list(ProspectDetails.objects.filter(won_on__gte=since, stage__is_won=True))
    lost = ProspectDetails.objects.filter(lost_on__gte=since, stage__is_lost=True).count()
    decided = len(won) + lost
    rate = round(100 * len(won) / decided) if decided else None
    spans = [
        (d.won_on - d.enquiry_date).days
        for d in won
        if d.enquiry_date and d.won_on and d.won_on >= d.enquiry_date
    ]
    return {
        "open_value": open_value,
        "weighted_value": weighted_value,
        "open_count": len(open_cards),
        "waiting": waiting,
        "win_rate": rate,
        "won_count": len(won),
        "lost_count": lost,
        "average_days": round(sum(spans) / len(spans)) if spans else None,
    }
