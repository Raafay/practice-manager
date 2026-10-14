"""Made-up onboarding data for development. Everything here is invented.

Three clients part-way through onboarding, one high-risk assessment waiting for
approval, and a few HMRC authorisations about to expire. Safe to run twice.
"""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import User
from apps.aml import demo as aml_demo
from apps.aml import services as aml
from apps.clients import services as client_services
from apps.clients.models import Client, ClientContact, Contact
from apps.core import actionlinks
from apps.core.models import ActionLink
from apps.services import services as service_services
from apps.services.models import Service

from . import hmrc, letters
from . import services as onboarding

PNG = b"\x89PNG\r\n\x1a\n" + b"demo-made-up" * 4

CLIENTS = [
    # name, type, contact first/last, stage
    ("Harbour Bakes Ltd", "ltd", ("Ines", "Harbour"), "started"),
    ("Quill and Pixel Ltd", "ltd", ("Quentin", "Quill"), "middle"),
    ("Meadow Fields Partnership", "partnership", ("Marta", "Meadow"), "nearly"),
]


def _client(name, client_type, person, manager):
    client = Client.objects.filter(name=name).first()
    if client:
        return client, False
    client = client_services.create_client(
        None,
        name=name,
        client_type=client_type,
        manager=manager,
        status=Client.Status.PROSPECT,
        email=f"hello.{person[1].lower()}@example.com",
        correspondence_address="1 Example Street\nSampletown\nZZ1 1ZZ",
    )
    first, last = person
    contact = Contact.objects.create(
        first_name=first, last_name=last, email=f"{first}.{last}@example.com".lower()
    )
    ClientContact.objects.create(
        client=client, contact=contact, is_main=True, can_sign=True, roles=["director"]
    )
    return client, True


def _verify_everyone(client, actor, how_many=None):
    aml.sync_checks(client)
    checks = list(aml.listed_checks(client))
    for check in checks[:how_many]:
        aml.upload_for_check(
            actor, check, SimpleUploadedFile("demo-id.png", PNG, content_type="image/png")
        )
        aml.update_check(
            actor, check, {"state": "verified", "method": "in_person", "document_type": "passport"}
        )


def _sign(client, actor):
    letter = letters.prepare_letter(actor, client)
    letters.send_letter(actor, letter)
    ActionLink.objects.filter(object_id=letter.pk).delete()
    link, _ = actionlinks.create(
        purpose=ActionLink.Purpose.SIGN_LETTER,
        contact=letter.signer,
        client=client,
        object_id=letter.pk,
    )
    letters.sign_letter(
        link, typed_name=letter.signer.full_name, agreed=True, ip="203.0.113.10", agent="Demo"
    )


def seed() -> dict:
    manager = User.objects.filter(role__slug="manager", is_active=True).order_by("pk").first()
    boss = User.objects.filter(role__slug="owner", is_active=True).order_by("pk").first()
    if manager is None or boss is None:
        return {"onboarding_clients": 0}
    made = 0
    accounts = Service.objects.filter(code="bookkeeping").first()
    for name, client_type, person, stage in CLIENTS:
        client, created = _client(name, client_type, person, manager)
        if not created:
            continue
        made += 1
        onboarding.on_proposal_accepted(client, actor=manager)
        if accounts and accounts.applies_to_type(client.client_type):
            service_services.switch_on(boss, client, accounts, fee_amount=95)
        if stage == "started":
            continue
        _sign(client, manager)
        if stage == "middle":
            _verify_everyone(client, manager)
            aml.start_assessment(manager, client)  # a draft, not yet submitted
            continue
        # nearly done: everything but "Services, fees and start dates confirmed"
        _verify_everyone(client, manager)
        onboarding.set_item(manager, client.onboarding_items.get(key="client_details"), "done")
        high = aml_demo.assess(client, "high", manager)  # waits for approval
        assert high.state == "submitted"
    _expiring(manager)
    return {"onboarding_clients": made}


def _expiring(manager) -> None:
    """Two requests that expire within a week, on clients that exist already."""
    today = timezone.localdate()
    if Client.objects.filter(agent_authorisations__isnull=False).exists():
        return
    clients = Client.objects.filter(status="active", client_type="ltd").order_by("name")[:2]
    for number, client in enumerate(clients):
        auth = hmrc.add(manager, client, tax="ct", method="post_code")
        if number == 0:
            hmrc.update(
                manager, auth, {"state": "requested", "requested_on": today - timedelta(days=25)}
            )
        else:
            hmrc.update(
                manager,
                auth,
                {
                    "state": "requested",
                    "method": "handshake",
                    "link_sent_on": today - timedelta(days=17),
                },
            )
