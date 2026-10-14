from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, sign_in, staff
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientFactory
from apps.events.models import ActivityEvent
from apps.onboarding import hmrc, jobs
from apps.onboarding.models import AgentAuthorisation
from apps.services import services as svc
from apps.services.models import Service

pytestmark = pytest.mark.django_db


def client_with(*codes):
    client = ClientFactory(status="prospect", client_type="ltd")
    client_services.change_status(manager(), client, "onboarding")
    for code in codes:
        svc.switch_on(manager(), client, Service.objects.get(code=code))
    return client


def test_which_taxes_a_service_needs():
    client = client_with("ct600", "payroll", "vat")
    names = dict(hmrc.needed(client))
    assert names["CT600 Return"] == ["ct"]
    assert names["Payroll"] == ["paye"]
    assert names["VAT Returns"] == ["vat", "mtd_vat"]


def test_postal_code_is_taken_to_expire_after_thirty_days():
    client = client_with("ct600")
    auth = hmrc.add(manager(), client, tax="ct", method="post_code")
    hmrc.update(manager(), auth, {"state": "requested", "requested_on": date(2026, 10, 1)})
    auth.refresh_from_db()
    assert auth.code_expires_on == date(2026, 10, 31)
    assert auth.link_expires_on is None
    # The date can be edited and is then left alone.
    hmrc.update(manager(), auth, {"state": "requested", "code_expires_on": date(2026, 11, 5)})
    auth.refresh_from_db()
    assert auth.code_expires_on == date(2026, 11, 5)


def test_handshake_link_expires_after_twenty_one_days():
    client = client_with("vat")
    auth = hmrc.add(manager(), client, tax="vat", method="handshake")
    hmrc.update(manager(), auth, {"state": "requested", "link_sent_on": date(2026, 10, 1)})
    auth.refresh_from_db()
    assert auth.link_expires_on == date(2026, 10, 22)
    assert auth.expiry == date(2026, 10, 22)


def test_manager_is_notified_seven_days_before_either_expiry_and_only_once():
    today = timezone.localdate()
    client = client_with("ct600", "vat")
    boss = manager()
    client.manager = boss
    client.save()
    code = hmrc.add(boss, client, tax="ct", method="post_code")
    hmrc.update(boss, code, {"state": "requested", "requested_on": today - timedelta(days=23)})
    link = hmrc.add(boss, client, tax="vat", method="handshake")
    hmrc.update(boss, link, {"state": "requested", "link_sent_on": today - timedelta(days=15)})
    assert hmrc.run_expiry(today) == {"notified": 2, "expired": 0}
    assert hmrc.run_expiry(today) == {"notified": 0, "expired": 0}
    assert boss.notifications.count() == 2
    assert {a.pk for a in hmrc.expiring(today)} == {code.pk, link.pk}
    # Not yet within seven days:
    other = client_with("ct600")
    fresh = hmrc.add(boss, other, tax="ct", method="post_code")
    hmrc.update(boss, fresh, {"state": "requested", "requested_on": today})
    assert fresh.pk not in {a.pk for a in hmrc.expiring(today)}


def test_requests_past_their_expiry_are_marked_expired():
    today = timezone.localdate()
    client = client_with("ct600")
    auth = hmrc.add(manager(), client, tax="ct", method="post_code")
    hmrc.update(manager(), auth, {"state": "requested", "requested_on": today - timedelta(days=40)})
    result = hmrc.run_expiry(today)
    auth.refresh_from_db()
    assert result["expired"] == 1 and auth.state == "expired"
    # A fresh request for the same tax can then be added.
    hmrc.add(manager(), client, tax="ct", method="handshake")


def test_checklist_ticks_when_every_needed_tax_is_authorised():
    client = client_with("ct600", "vat")
    ct = hmrc.add(manager(), client, tax="ct", method="post_code")
    vat = hmrc.add(manager(), client, tax="mtd_vat", method="handshake")
    line = client.onboarding_items.get(key="hmrc_authorisations")
    hmrc.update(manager(), ct, {"state": "authorised"})
    line.refresh_from_db()
    assert line.state == "todo"
    hmrc.update(manager(), vat, {"state": "authorised"})  # MTD VAT satisfies the VAT service
    line.refresh_from_db()
    assert line.state == "done"
    hmrc.update(manager(), ct, {"state": "rejected"})
    line.refresh_from_db()
    assert line.state == "todo"


def test_the_code_is_encrypted_shown_masked_and_revealing_is_logged(client):
    c = client_with("ct600")
    auth = hmrc.add(manager(), c, tax="ct", method="post_code")
    sign_in(client, staff())
    response = client.post(
        reverse("onboarding:hmrc_edit", args=[c.pk, auth.pk]),
        {"state": "code_received", "method": "post_code", "code": "ABCD1234ZX"},
    )
    assert response.status_code == 302
    auth.refresh_from_db()
    assert auth.code == "ABCD1234ZX"
    page = client.get(reverse("onboarding:hmrc", args=[c.pk])).content.decode()
    assert "ABCD1234ZX" not in page and "••••" in page
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("select code from onboarding_agentauthorisation where id=%s", [auth.pk])
        assert "ABCD1234ZX" not in cursor.fetchone()[0]
    shown = client.post(reverse("onboarding:hmrc_reveal", args=[c.pk, auth.pk]))
    assert b"ABCD1234ZX" in shown.content and shown["Cache-Control"] == "no-store"
    event = ActivityEvent.objects.get(verb="sensitive.revealed", client=c)
    assert "ABCD1234ZX" not in event.summary and "ABCD1234ZX" not in str(event.data)


def test_hmrc_pages_need_sign_in_and_belong_to_the_client(client):
    c = client_with("ct600")
    auth = hmrc.add(manager(), c, tax="ct", method="post_code")
    urls = [
        reverse("onboarding:hmrc", args=[c.pk]),
        reverse("onboarding:hmrc_add", args=[c.pk]),
        reverse("onboarding:hmrc_edit", args=[c.pk, auth.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 302
    assert client.post(reverse("onboarding:hmrc_reveal", args=[c.pk, auth.pk])).status_code == 302
    sign_in(client, staff())
    for url in urls:
        assert client.get(url).status_code == 200
    other = ClientFactory()
    assert client.get(reverse("onboarding:hmrc_edit", args=[other.pk, auth.pk])).status_code == 404
    assert AgentAuthorisation.objects.count() == 1


def test_letter_review_task_thirty_days_before(client):
    from apps.onboarding import letters
    from apps.onboarding.tests.test_letters import new_token, sent_letter
    from apps.tasks.models import Task

    c, contact, letter = sent_letter()
    link, token = new_token(letter)
    done = letters.sign_letter(link, typed_name="Sam Sample", agreed=True, ip=None, agent="")
    assert jobs.create_letter_review_tasks() == 0
    done.review_due = timezone.localdate() + timedelta(days=20)
    done.save()
    assert jobs.create_letter_review_tasks() == 1
    assert jobs.create_letter_review_tasks() == 0
    assert Task.objects.filter(title=f"Engagement letter review: {c.name}").exists()
