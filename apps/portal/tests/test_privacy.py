"""Spec 08 section 7: what a portal user must never see."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager
from apps.aml.models import RiskAssessment
from apps.clients import services as client_services
from apps.clients.models import ClientContact
from apps.clients.tests.factories import ClientFactory, ContactFactory, DocumentFactory
from apps.portal import services
from apps.portal.models import PortalItem
from apps.portal.tests.helpers import portal_login, portal_person
from apps.services import services as svc
from apps.services.models import Service
from apps.tasks import services as task_services
from apps.tasks.tests.factories import make_task

pytestmark = pytest.mark.django_db

SECRETS = {
    "fee": "4321.98",
    "fee_formatted": "4,321.98",
    "note": "INTERNAL-NOTE-MARKER",
    "comment": "TASK-COMMENT-MARKER",
    "risk": "RISK-SUMMARY-MARKER",
    "colleague_home": "COLLEAGUE-HOME-MARKER",
    "colleague_phone": "07700-900-MARKER",
    "colleague_email": "colleague.marker@example.com",
    "colleague_dob": "1971-04-05",
    "staff_doc": "STAFF-ONLY-DOC-MARKER",
    "other_client": "OTHER-CLIENT-MARKER",
    "owner_name": "Hidden Staffname",
}


@pytest.fixture
def world(client):
    boss = manager(name="Hidden Staffname")
    cl = ClientFactory(name="Alpha Ltd", manager=boss)
    user, contact, _ = portal_person(cl, first_name="Sam", last_name="Sample")
    other_client = ClientFactory(name=SECRETS["other_client"])
    colleague = ContactFactory(
        first_name="Casey",
        last_name="Colleague",
        email=SECRETS["colleague_email"],
        mobile=SECRETS["colleague_phone"],
        home_address=SECRETS["colleague_home"],
        date_of_birth="1971-04-05",
        ni_number="ZZ 99 99 99 Z",
    )
    ClientContact.objects.create(client=cl, contact=colleague, roles=["director"])
    service = Service.objects.filter(code="accounts").first() or Service.objects.first()
    svc.switch_on(boss, cl, service, fee_amount="4321.98")
    client_services.add_note(boss, cl, SECRETS["note"])
    task = make_task(boss, client=cl, owner=boss, title="Prepare accounts")
    task_services.add_comment(boss, task, SECRETS["comment"])
    RiskAssessment.objects.create(client=cl, summary=SECRETS["risk"], level="high")
    DocumentFactory(client=cl, title=SECRETS["staff_doc"], shared_with_portal=False)
    DocumentFactory(client=cl, title="Shared accounts", shared_with_portal=True)
    DocumentFactory(client=other_client, title="Other client's file", shared_with_portal=True)
    services.create_item(boss, cl, PortalItem.Kind.UPLOAD_RECORDS, "Upload your records", task=task)
    services.create_item(boss, cl, PortalItem.Kind.CONFIRM_DETAILS, "Check your details", task=task)
    services.create_item(boss, cl, PortalItem.Kind.CLIENT_DETAILS, "Your details", reuse=False)
    portal_login(client, user)
    return {"cl": cl, "user": user, "http": client}


def all_portal_pages(w):
    http, cl = w["http"], w["cl"]
    pages = {
        name: http.get(reverse(f"portal:{name}")) for name in ("home", "documents", "requests")
    }
    pages["details"] = http.get(reverse("portal:details"))
    pages["request_new"] = http.get(reverse("portal:request_new"))
    for item in PortalItem.objects.filter(client=cl):
        pages[f"item {item.kind}"] = http.get(
            reverse("portal:item", args=[item.public_id]), follow=True
        )
        if item.kind in ("confirm_details", "client_details"):
            pages[f"form {item.kind}"] = http.get(reverse("portal:form", args=[item.public_id]))
    return pages


def test_no_portal_page_shows_internal_information(world):
    pages = all_portal_pages(world)
    assert len(pages) >= 9
    for name, response in pages.items():
        assert response.status_code == 200, name
        text = response.content.decode()
        for label, secret in SECRETS.items():
            assert secret not in text, f"{name} shows {label}"
        for word in ("Fees", "Time logged", "Risk assessment", "Hidden Staffname"):
            assert word not in text, f"{name} mentions {word}"


def test_the_details_page_lists_colleagues_by_name_and_role_only(world):
    text = world["http"].get(reverse("portal:details")).content.decode()
    assert "Casey Colleague" in text and "Director" in text
    assert SECRETS["colleague_email"] not in text and SECRETS["colleague_home"] not in text
    assert "99 99 99" not in text
