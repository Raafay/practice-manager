"""The onboarding checklist and the go-live gate (spec 06 section 1)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps import events
from apps.clients import services as client_services
from apps.clients.models import Client

from .models import ChecklistTemplateItem, OnboardingItem

State = OnboardingItem.State


def who(actor) -> str:
    return str(actor) if actor is not None else "The system"


def ensure_checklist(client: Client) -> int:
    """Make any checklist lines the client lacks. Safe to run twice. Returns how many were made."""
    have = set(client.onboarding_items.values_list("key", flat=True))
    made = 0
    for line in ChecklistTemplateItem.objects.filter(active=True):
        if line.key in have:
            continue
        OnboardingItem.objects.create(
            client=client,
            key=line.key,
            name=line.name,
            needed_before_golive=line.needed_before_golive,
            set_by_system=line.system_ticked,
            position=line.position,
        )
        made += 1
    if made and not have:
        events.record(
            None,
            "onboarding.started",
            f"Onboarding checklist created for {client.name}.",
            client=client,
            target=client,
        )
    return made


def start_onboarding(actor, client: Client) -> Client:
    """Move a prospect to onboarding and create its checklist."""
    if client.status == Client.Status.PROSPECT:
        client_services.set_status(actor, client, Client.Status.ONBOARDING)
    ensure_checklist(client)
    return client


def on_proposal_accepted(client: Client, actor=None) -> None:
    """Called by Stage 9 when a proposal is accepted."""
    start_onboarding(actor, client)
    tick(client, "proposal_accepted", actor=actor, note="Proposal accepted.", auto=True)


def _find(client: Client, key: str) -> OnboardingItem | None:
    return client.onboarding_items.filter(key=key).first()


def tick(client: Client, key: str, *, actor=None, note: str = "", auto: bool = False) -> bool:
    """Mark a line done. Does nothing if the client has no such line or it is finished."""
    item = _find(client, key)
    if item is None or item.is_finished:
        return False
    item.state = State.DONE
    item.done_on = timezone.localdate()
    item.done_by = actor
    item.auto_ticked = auto
    if note:
        item.note = note[:300]
    item.save()
    events.record(
        actor,
        "onboarding.ticked",
        f"{item.name} was ticked for {client.name}"
        + (f" by {actor}." if actor is not None else " by the system."),
        client=client,
        target=item,
        key=key,
    )
    return True


def sync_system_item(client: Client, key: str, ok: bool, *, actor=None, note: str = "") -> None:
    """Tick a line when its condition holds; put it back to "to do" if it stops holding.

    Only a line the system ticked is put back. One set by hand, or marked not needed, stays.
    """
    item = _find(client, key)
    if item is None:
        return
    if ok:
        tick(client, key, actor=actor, note=note, auto=True)
    elif item.state == State.DONE and item.auto_ticked:
        item.state = State.TODO
        item.auto_ticked = False
        item.done_on = None
        item.done_by = None
        item.save()
        events.record(
            actor,
            "onboarding.unticked",
            f"{item.name} was put back to “to do” for {client.name}: it no longer holds.",
            client=client,
            target=item,
            key=key,
        )


def set_item(actor, item: OnboardingItem, state: str, note: str = "") -> OnboardingItem:
    if state not in State.values:
        raise ValidationError("Choose a state.")
    old = item.state
    item.state = state
    item.note = note[:300]
    item.auto_ticked = False
    if state == State.DONE:
        item.done_on = item.done_on or timezone.localdate()
        item.done_by = actor
    elif state != State.NOT_NEEDED:
        item.done_on = None
        item.done_by = None
    item.save()
    if old != state or note:
        events.record(
            actor,
            "onboarding.item_changed",
            f"{who(actor)} set “{item.name}” to {State(state).label.lower()} for "
            f"{item.client.name}.",
            client=item.client,
            target=item,
            old=old,
            new=state,
        )
    return item


def gate_problems(client: Client) -> list[str]:
    """Names of the lines needed before go-live that are still open."""
    return [
        item.name
        for item in client.onboarding_items.filter(needed_before_golive=True)
        if not item.is_finished
    ]


def progress(client: Client) -> dict:
    items = list(client.onboarding_items.all())
    done = [i for i in items if i.is_finished]
    needed = [i for i in items if i.needed_before_golive]
    return {
        "total": len(items),
        "done": len(done),
        "needed": len(needed),
        "needed_done": len([i for i in needed if i.is_finished]),
        "percent": int(100 * len(done) / len(items)) if items else 0,
    }


@transaction.atomic
def make_live(actor, client: Client, *, override_reason: str = "") -> Client:
    """Make an onboarding client active. The gate must be clear, or the actor may override it."""
    if not actor.can("clients.status"):
        raise PermissionDenied
    client = Client.objects.select_for_update().get(pk=client.pk)
    if client.status != Client.Status.ONBOARDING:
        raise ValidationError("Only a client in onboarding can be made live.")
    problems = gate_problems(client)
    override_reason = override_reason.strip()
    if problems:
        if not actor.can("onboarding.override"):
            raise ValidationError("Not ready to go live: " + "; ".join(problems) + ".")
        if not override_reason:
            raise ValidationError("Give a reason for making this client live early.")
    client_services.set_status(actor, client, Client.Status.ACTIVE, reason=override_reason)
    if problems:
        events.record(
            actor,
            "onboarding.override",
            f"{who(actor)} made {client.name} live early, with {len(problems)} item"
            f"{'s' if len(problems) != 1 else ''} open ({'; '.join(problems)}). "
            f"Reason: {override_reason}",
            client=client,
            target=client,
            reason=override_reason,
            open_items=problems,
        )
    else:
        events.record(
            actor,
            "onboarding.made_live",
            f"{who(actor)} made {client.name} live.",
            client=client,
            target=client,
        )
    return client
