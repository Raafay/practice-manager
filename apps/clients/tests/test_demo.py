import io

import pytest
from django.core.management import call_command

from apps.clients.models import Client, ClientContact, Contact, Document

pytestmark = pytest.mark.django_db


def test_demo_data_covers_every_type_and_status_and_is_safe_to_run_twice():
    call_command("seed_demo", stdout=io.StringIO())
    first = (Client.objects.count(), Contact.objects.count(), Document.objects.count())
    call_command("seed_demo", stdout=io.StringIO())
    assert first == (Client.objects.count(), Contact.objects.count(), Document.objects.count())
    # Stage 7 adds three onboarding contacts to the fifty from Stage 2.
    assert first[0] >= 30 and first[1] >= 50 and first[2] > 0
    assert set(Client.objects.values_list("client_type", flat=True)) == {
        value for value, _ in Client.Type.choices
    }
    assert set(Client.objects.values_list("status", flat=True)) == {
        value for value, _ in Client.Status.choices
    }
    # Some people are shared between clients, and every client has at most one main contact.
    shared = Contact.objects.filter(client_links__isnull=False).distinct().count()
    assert ClientContact.objects.count() > shared
    assert ClientContact.objects.filter(is_main=True).count() == Client.objects.count()
    # Identity documents in the demo are flagged sensitive.
    assert Document.objects.filter(category="identity", sensitive=True).exists()
