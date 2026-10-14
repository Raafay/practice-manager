import io

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.portal.models import PortalForm, PortalItem, Request

pytestmark = pytest.mark.django_db


def test_demo_covers_the_portal_and_is_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = (PortalItem.objects.count(), Request.objects.count(), User.objects.count())
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (PortalItem.objects.count(), Request.objects.count(), User.objects.count())
    portal_users = User.objects.filter(kind="portal")
    assert portal_users.count() >= 2
    clients = {link.client_id for u in portal_users for link in u.portal_contact.client_links.all()}
    assert len(clients) >= 2
    open_kinds = set(PortalItem.objects.filter(state="open").values_list("kind", flat=True))
    assert open_kinds == {
        "sign_letter", "accept_proposal", "upload_records", "confirm_details",
        "client_details", "approve_document",
    }  # fmt: skip
    assert PortalForm.objects.filter(state="submitted", kind="confirmation").exists()
    assert Request.objects.count() == 15
    assert set(Request.objects.values_list("channel", flat=True)) >= {
        "form", "portal", "email", "whatsapp", "phone", "in_person",
    }  # fmt: skip
    assert set(Request.objects.values_list("state", flat=True)) == {
        "new", "in_progress", "answered", "closed", "spam",
    }  # fmt: skip
    assert Request.objects.filter(task__isnull=False).count() >= 3
