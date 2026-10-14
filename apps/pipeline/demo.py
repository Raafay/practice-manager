"""Made-up sales data for development. Everything here is invented. Safe to run twice.

Twelve open prospects spread over the stages (some quiet, some with meetings), three
proposals in different states, two won and three lost in the last year with reasons.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.clients import services as client_services
from apps.clients.models import Client, ClientContact, Contact
from apps.core.models import ActionLink
from apps.services import services as service_services
from apps.services.models import Service

from . import proposals, services
from .models import ProspectDetails

# name, type, (first, last), stage key, source, next action, days until it is due, fee
OPEN = [
    (
        "Fernhill Plumbing Ltd",
        "ltd",
        ("Fay", "Fernhill"),
        "enquiry",
        "website",
        "Call back",
        2,
        180,
    ),
    (
        "Orchard Row Studio Ltd",
        "ltd",
        ("Olive", "Orchard"),
        "enquiry",
        "word_of_mouth",
        "Reply",
        -3,
        120,
    ),
    (
        "Bluebell Care Partnership",
        "partnership",
        ("Ben", "Bluebell"),
        "meeting_booked",
        "client_referral",
        "Prepare for meeting",
        4,
        250,
    ),
    (
        "Tidewater Surveys Ltd",
        "ltd",
        ("Tess", "Tidewater"),
        "meeting_booked",
        "website",
        "Confirm time",
        1,
        200,
    ),
    (
        "Larkspur Design Ltd",
        "ltd",
        ("Lars", "Larkspur"),
        "meeting_held",
        "accountant_referral",
        "Send prices",
        -5,
        300,
    ),
    (
        "Millstone Joinery",
        "sole_trader",
        ("Max", "Millstone"),
        "meeting_held",
        "word_of_mouth",
        "Ring about services",
        6,
        90,
    ),
    (
        "Copperfield Events Ltd",
        "ltd",
        ("Cora", "Copperfield"),
        "follow_up",
        "client_referral",
        "Second meeting",
        3,
        400,
    ),
    ("Saltmarsh Catering Ltd", "ltd", ("Sal", "Saltmarsh"), "follow_up", "other", "", None, 220),
    (
        "Quarry Lane Cycles Ltd",
        "ltd",
        ("Quin", "Quarry"),
        "proposal_sent",
        "word_of_mouth",
        "Chase proposal",
        5,
        350,
    ),
    (
        "Wren and Finch Ltd",
        "ltd",
        ("Wynne", "Finch"),
        "proposal_sent",
        "website",
        "Chase proposal",
        7,
        275,
    ),
    (
        "Hollow Oak Farm",
        "sole_trader",
        ("Hal", "Oakley"),
        "on_hold",
        "client_referral",
        "Ask again in spring",
        60,
        100,
    ),
    ("Ironbridge Print Ltd", "ltd", ("Iris", "Ironbridge"), "enquiry", "other", "Reply", 2, 150),
]

WON = [
    ("Daybreak Bakery Ltd", "ltd", ("Dana", "Daybreak"), 25, 260),
    ("Kestrel Logistics Ltd", "ltd", ("Kit", "Kestrel"), 120, 330),
]

LOST = [
    ("Marlow Pottery Ltd", "ltd", ("Mia", "Marlow"), 20, "price"),
    ("Nightjar Media Ltd", "ltd", ("Ned", "Nightjar"), 90, "went_elsewhere"),
    ("Pebble Street Cafe", "sole_trader", ("Pam", "Pebble"), 200, "timing"),
]


def _owners() -> list[User]:
    people = list(User.objects.staff().filter(is_active=True).order_by("pk"))
    return people or [None]


def _make(name, client_type, person, owner, source):
    client = Client.objects.filter(name=name).first()
    if client:
        return client, False
    first, last = person
    contact = Contact.objects.create(
        first_name=first, last_name=last, email=f"{first}.{last}@example.com".lower()
    )
    client = client_services.create_client(
        None,
        name=name,
        client_type=client_type,
        manager=owner,
        status=Client.Status.PROSPECT,
        source=source,
    )
    ClientContact.objects.create(
        client=client, contact=contact, is_main=True, can_sign=True, roles=["director"]
    )
    return client, True


def _propose(client, fee: int, owner):
    """Tick a couple of services as proposed, summing to roughly the fee."""
    codes = ["accounts", "bookkeeping", "vat", "payroll"]
    chosen = list(Service.objects.filter(code__in=codes)[:2]) or list(Service.objects.all()[:2])
    split = [Decimal(fee) * Decimal("0.6"), Decimal(fee) * Decimal("0.4")]
    for service, part in zip(chosen, split, strict=False):
        service_services.switch_on(owner, client, service, fee_amount=part.quantize(Decimal("1")))


def seed() -> dict:
    owners = _owners()
    made = {"prospects": 0, "meetings": 0, "proposals": 0, "won": 0, "lost": 0}
    now = timezone.now()
    today = timezone.localdate()
    owner_for = lambda i: owners[i % len(owners)]  # noqa: E731

    for index, row in enumerate(OPEN):
        name, kind, person, stage_key, source, action, due, fee = row
        owner = owner_for(index)
        client, new = _make(name, kind, person, owner, source)
        if not new:
            continue
        made["prospects"] += 1
        details = services.ensure_details(client)
        stage = details.stage.__class__.objects.get(key=stage_key)
        details.stage = stage
        details.owner = owner
        details.enquiry_date = today - timedelta(days=10 + index * 4)
        details.stage_changed_at = now - timedelta(days=2 + index)
        details.expected_fee = Decimal(fee)
        details.next_action = action
        details.next_action_date = today + timedelta(days=due) if due is not None else None
        details.expected_start = (today + timedelta(days=45)).replace(day=1)
        details.last_activity_at = now - timedelta(days=1 + index % 5)
        if name == "Saltmarsh Catering Ltd":  # quiet through inactivity alone
            details.last_activity_at = now - timedelta(days=21)
        details.save()
        if name == "Saltmarsh Catering Ltd":
            ProspectDetails.objects.filter(pk=details.pk).update(
                created_at=now - timedelta(days=30)
            )
        if stage_key in ("meeting_held", "follow_up", "proposal_sent") and "Saltmarsh" not in name:
            meeting = services.log_meeting(
                owner,
                client,
                held_at=now - timedelta(days=3 + index),
                kind="face_to_face",
                place="Our office",
                staff=[owner] if owner else [],
                people=person[0] + " " + person[1],
                notes="Talked through the business and what they need help with.",
                outcome="Keen to hear a price",
                follow_up="Send a proposal" if stage_key == "meeting_held" else "",
                follow_up_date=today + timedelta(days=3) if stage_key == "meeting_held" else None,
            )
            made["meetings"] += 1
            # log_meeting restarts the clock; put the stage and dates back as set above.
            ProspectDetails.objects.filter(pk=details.pk).update(
                stage=stage,
                next_action=action,
                next_action_date=details.next_action_date,
                last_activity_at=details.last_activity_at,
            )
            _ = meeting
        if stage_key in ("follow_up", "proposal_sent"):
            _propose(client, fee, owner)

    # Three proposals in different states.
    for name, state in (
        ("Quarry Lane Cycles Ltd", "viewed"),
        ("Wren and Finch Ltd", "sent"),
        ("Copperfield Events Ltd", "declined"),
    ):
        client = Client.objects.filter(name=name).first()
        if client is None or client.proposals.exists():
            continue
        owner = owner_for(0)
        proposal = proposals.create_proposal(owner, client)
        subject, html = proposals.default_message(proposal, owner)
        proposals.send_proposal(
            owner,
            proposal,
            to=proposal.contact.email,
            cc="",
            subject=subject,
            body_html=html,
        )
        proposal.refresh_from_db()
        link = ActionLink.objects.filter(purpose="proposal", object_id=proposal.pk).first()
        if state == "viewed":
            proposals.note_viewed(proposal, link)
        elif state == "declined" and link is not None:
            proposals.decline(
                link,
                reason="We have decided to stay with our current accountant.",
                ip=None,
                agent="",
            )
            # A declined proposal leaves the prospect where it was.
            follow = ProspectDetails.objects.get(client=client)
            follow.stage = follow.stage.__class__.objects.get(key="follow_up")
            follow.save(update_fields=["stage", "updated_at"])
        made["proposals"] += 1

    # Two won (one with an accepted proposal) and three lost in the last year.
    for index, (name, kind, person, days_ago, fee) in enumerate(WON):
        client, new = _make(name, kind, person, owner_for(index), "word_of_mouth")
        if not new:
            continue
        details = services.ensure_details(client)
        details.enquiry_date = today - timedelta(days=days_ago + 30)
        details.expected_fee = Decimal(fee)
        details.owner = owner_for(index)
        details.save()
        _propose(client, fee, owner_for(index))
        if index == 0:
            proposal = proposals.create_proposal(owner_for(index), client)
            subject, html = proposals.default_message(proposal, owner_for(index))
            proposals.send_proposal(
                owner_for(index),
                proposal,
                to=proposal.contact.email,
                subject=subject,
                body_html=html,
            )
            link = ActionLink.objects.filter(purpose="proposal", object_id=proposal.pk).first()
            proposals.accept(
                link,
                typed_name=f"{person[0]} {person[1]}",
                agreed=True,
                ip="203.0.113.7",
                agent="Demo",
            )
            made["proposals"] += 1
        else:
            services.move_stage(owner_for(index), client, services.stage_of_kind(won=True))
        ProspectDetails.objects.filter(client=client).update(
            won_on=today - timedelta(days=days_ago)
        )
        made["won"] += 1

    for index, (name, kind, person, days_ago, reason) in enumerate(LOST):
        client, new = _make(name, kind, person, owner_for(index), "website")
        if not new:
            continue
        details = services.ensure_details(client)
        details.enquiry_date = today - timedelta(days=days_ago + 20)
        details.expected_fee = Decimal(150 + index * 50)
        details.owner = owner_for(index)
        details.save()
        services.move_stage(
            owner_for(index),
            client,
            services.stage_of_kind(lost=True),
            lost_reason=reason,
            lost_note="Made up for the demo.",
        )
        ProspectDetails.objects.filter(client=client).update(
            lost_on=today - timedelta(days=days_ago)
        )
        made["lost"] += 1
    return made
