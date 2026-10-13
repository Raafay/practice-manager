"""Working out which deadlines each client should have, and acting on them.

`generate_for_client` is the one entry point for creating deadlines. It is safe to
run twice: periods are matched on client, rule and period key (CORRECTIONS 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps import events
from apps.clients.models import Client

from .models import ClientService, Deadline
from .rules import REGISTRY, Inputs, Period

# A service that started long ago is not given years of overdue history (assumption,
# see STATUS.md). Periods due more than this many days ago are not created.
LOOKBACK_DAYS = 60

CH_RULES = {
    "ch_accounts": "last_accounts_made_up_to",
    "confirmation_statement": "last_statement_made_up_to",
}


@dataclass
class Result:
    created: list[Deadline] = field(default_factory=list)
    updated: list[Deadline] = field(default_factory=list)
    done: list[Deadline] = field(default_factory=list)
    not_required: list[Deadline] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.created or self.updated or self.done or self.not_required)

    def merge(self, other: Result) -> None:
        self.created += other.created
        self.updated += other.updated
        self.done += other.done
        self.not_required += other.not_required


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


# ------------------------------------------------------------------ inputs


def inputs_for(client: Client, cs: ClientService, today: date) -> Inputs:
    return Inputs(
        today=today,
        start=cs.starts_on,
        incorporated_on=client.incorporated_on,
        last_accounts_made_up_to=client.last_accounts_made_up_to,
        next_accounts_made_up_to=client.next_accounts_made_up_to,
        next_accounts_due=client.next_accounts_due,
        last_statement_made_up_to=client.last_statement_made_up_to,
        next_statement_made_up_to=client.next_statement_made_up_to,
        next_statement_due=client.next_statement_due,
        vat_frequency=client.vat_frequency,
        vat_stagger=client.vat_stagger,
        vat_scheme=client.vat_scheme,
        vat_year_end_month=client.vat_year_end_month,
        payroll_frequency=client.payroll_frequency,
        pay_day_rule=client.pay_day_rule,
        pay_day=client.pay_day,
        first_pay_date=client.first_pay_date,
        payments_on_account=client.payments_on_account,
        mtd_start=client.mtd_start,
        auto_enrolment_start=client.auto_enrolment_start,
        last_reenrolment=client.last_reenrolment,
        settings=dict(cs.settings or {}),
    )


def wanted_periods(client: Client, cs: ClientService, rule_name: str, today: date) -> list[Period]:
    """The periods this client service should have today for one rule."""
    info = REGISTRY.get(rule_name)
    if info is None:
        return []
    start = cs.starts_on or cs.created_at.date()
    earliest = max(start, today - timedelta(days=LOOKBACK_DAYS))
    periods = []
    for period in info.func(inputs_for(client, cs, today)):
        if not info.always_current and period.due_date < earliest:
            continue
        if cs.ends_on and (period.period_end or period.due_date) > cs.ends_on:
            continue
        periods.append(period)
    return periods


# ------------------------------------------------------------------ generation


def generate_for_client(client: Client, *, today: date | None = None, actor=None) -> Result:
    """Create the deadlines a client is missing and bring open ones up to date.

    Only live clients get new deadlines: a paused or former client gets nothing new,
    and open ones stay until staff mark them.
    """
    today = today or timezone.localdate()
    result = Result()
    if client.archived_at is not None or client.status != Client.Status.ACTIVE:
        return result
    rows = client.client_services.filter(state=ClientService.State.ACTIVE).select_related("service")
    with transaction.atomic():
        for cs in rows:
            for rule_name in cs.service.rules:
                result.merge(_apply_rule(client, cs, rule_name, today, actor))
    if result.created:
        events.record(
            actor,
            "deadline.generated",
            f"{len(result.created)} deadline{'s' if len(result.created) != 1 else ''} "
            f"created for {client.name}.",
            client=client,
            labels=[f"{d.label} ({d.rule_title})" for d in result.created][:20],
        )
    return result


def generate_all(*, today: date | None = None) -> dict:
    counts = {"clients": 0, "created": 0, "updated": 0, "done": 0}
    clients = Client.objects.not_archived().filter(
        status=Client.Status.ACTIVE, client_services__state=ClientService.State.ACTIVE
    )
    for client in clients.distinct().order_by("pk"):
        result = generate_for_client(client, today=today)
        counts["clients"] += 1
        counts["created"] += len(result.created)
        counts["updated"] += len(result.updated)
        counts["done"] += len(result.done)
    return counts


def _apply_rule(client, cs, rule_name, today, actor) -> Result:
    result = Result()
    periods = wanted_periods(client, cs, rule_name, today)
    if rule_name in CH_RULES:
        _filings_seen(client, cs, rule_name, today, actor, result)
        if periods:
            _move_open_period(client, cs, rule_name, periods[0], actor, result)
    for period in periods:
        _apply_period(client, cs, rule_name, period, actor, result)
    return result


def _apply_period(client, cs, rule_name, period: Period, actor, result: Result) -> None:
    row = Deadline.objects.filter(client=client, rule=rule_name, period_key=period.key).first()
    if row is None:
        row = Deadline.objects.create(
            client=client,
            client_service=cs,
            rule=rule_name,
            period_key=period.key,
            label=period.label,
            period_start=period.period_start,
            period_end=period.period_end,
            due_date=period.due_date,
            original_due_date=period.due_date,
            source=period.source,
            source_note=period.note,
        )
        result.created.append(row)
        return
    if row.client_service_id is None:
        row.client_service = cs
        row.save(update_fields=["client_service", "updated_at"])
    if row.status != Deadline.Status.OPEN or row.source == Deadline.Source.MANUAL:
        return
    changed = _refresh(row, period)
    if changed:
        events.record(
            actor,
            "deadline.updated",
            f"{row.label}: due date changed from {fmt(changed['due_date'])} to "
            f"{fmt(row.due_date)} for {client.name}.",
            client=client,
            target=row,
            old=changed["due_date"],
            new=row.due_date,
            source=row.source,
        )
        result.updated.append(row)


def _refresh(row: Deadline, period: Period) -> dict | None:
    """Bring an open, unedited deadline in line with its rule. Returns the old due date."""
    if (
        row.due_date == period.due_date
        and row.label == period.label
        and row.period_start == period.period_start
        and row.source == period.source
        and row.source_note == period.note
    ):
        return None
    old = {"due_date": row.due_date}
    row.due_date = row.original_due_date = period.due_date
    row.label = period.label
    row.period_start = period.period_start
    row.source = period.source
    row.source_note = period.note
    row.save()
    return old


def _filings_seen(client, cs, rule_name, today, actor, result: Result) -> None:
    """Mark an open Companies House deadline done once the filing shows."""
    last = getattr(client, CH_RULES[rule_name])
    if not last:
        return
    for row in Deadline.objects.filter(client=client, rule=rule_name, status=Deadline.Status.OPEN):
        if row.period_end and last >= row.period_end:
            row.status = Deadline.Status.DONE
            row.done_on = today
            row.evidence = f"Shown as filed at Companies House, seen {fmt(today)}"
            row.save()
            events.record(
                actor,
                "deadline.done",
                f"{row.label} marked done for {client.name}: {row.evidence}.",
                client=client,
                target=row,
                automatic=True,
            )
            result.done.append(row)


def _move_open_period(client, cs, rule_name, period: Period, actor, result: Result) -> None:
    """The year end moved with no filing: update the open deadline in place."""
    if Deadline.objects.filter(client=client, rule=rule_name, period_key=period.key).exists():
        return
    row = (
        Deadline.objects.filter(client=client, rule=rule_name, status=Deadline.Status.OPEN)
        .order_by("due_date")
        .first()
    )
    if row is None:
        return
    old_end = row.period_end
    row.period_key = period.key
    row.period_end = period.period_end
    row.period_start = period.period_start
    row.label = period.label
    old_due = row.due_date
    row.due_date = row.original_due_date = period.due_date
    row.source = period.source
    row.source_note = period.note
    row.save()
    events.record(
        actor,
        "deadline.updated",
        f"Companies House: period end for {row.rule_title} moved from {fmt(old_end)} "
        f"to {fmt(period.period_end)}; due {fmt(old_due)} became {fmt(period.due_date)} "
        f"for {client.name}.",
        client=client,
        target=row,
        old_period_end=old_end,
        new_period_end=period.period_end,
    )
    result.updated.append(row)


# ------------------------------------------------------------------ actions


def _not_open(deadline: Deadline) -> ValidationError:
    return ValidationError("This deadline is not open. Reopen it first.")


def mark_done(
    actor, deadline: Deadline, *, done_on: date | None = None, note: str = ""
) -> Deadline:
    if not deadline.is_open:
        raise _not_open(deadline)
    deadline.status = Deadline.Status.DONE
    deadline.done_on = done_on or timezone.localdate()
    deadline.done_by = actor
    deadline.done_note = note.strip()[:500]
    deadline.save()
    events.record(
        actor,
        "deadline.done",
        f"{actor} marked {deadline.label} ({deadline.rule_title}) done on {fmt(deadline.done_on)}.",
        client=deadline.client,
        target=deadline,
        note=deadline.done_note,
    )
    return deadline


def mark_not_required(actor, deadline: Deadline, *, reason: str) -> Deadline:
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say why this deadline is not required.")
    if not deadline.is_open:
        raise _not_open(deadline)
    deadline.status = Deadline.Status.NOT_REQUIRED
    deadline.override_reason = reason[:300]
    deadline.done_by = actor
    deadline.save()
    events.record(
        actor,
        "deadline.not_required",
        f"{actor} marked {deadline.label} ({deadline.rule_title}) not required: {reason}",
        client=deadline.client,
        target=deadline,
        reason=reason,
    )
    return deadline


def reopen(actor, deadline: Deadline) -> Deadline:
    if deadline.is_open:
        raise ValidationError("This deadline is already open.")
    previous = deadline.status
    deadline.status = Deadline.Status.OPEN
    deadline.done_on = None
    deadline.done_by = None
    deadline.done_note = ""
    deadline.evidence = ""
    if previous == Deadline.Status.NOT_REQUIRED and deadline.source != Deadline.Source.MANUAL:
        deadline.override_reason = ""
    deadline.save()
    events.record(
        actor,
        "deadline.reopened",
        f"{actor} reopened {deadline.label} ({deadline.rule_title}).",
        client=deadline.client,
        target=deadline,
        previous=previous,
    )
    return deadline


def change_due_date(actor, deadline: Deadline, new_date: date, *, reason: str) -> Deadline:
    reason = reason.strip()
    if not reason:
        raise ValidationError("Say why the date is being changed.")
    if deadline.source == Deadline.Source.COMPANIES_HOUSE:
        raise ValidationError("This date comes from Companies House and cannot be changed by hand.")
    if not deadline.is_open:
        raise _not_open(deadline)
    if new_date == deadline.due_date:
        raise ValidationError("That is already the due date.")
    old = deadline.due_date
    deadline.due_date = new_date  # original_due_date keeps the calculated date
    deadline.source = Deadline.Source.MANUAL
    deadline.override_reason = reason[:300]
    deadline.source_note = f"Changed by hand from {fmt(deadline.original_due_date)}: {reason}"[:300]
    deadline.save()
    events.record(
        actor,
        "deadline.date_changed",
        f"{actor} changed the due date of {deadline.label} ({deadline.rule_title}) "
        f"from {fmt(old)} to {fmt(new_date)}: {reason}",
        client=deadline.client,
        target=deadline,
        old=old,
        new=new_date,
        original=deadline.original_due_date,
        reason=reason,
    )
    return deadline
