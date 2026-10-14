from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.aml import jobs, services
from apps.aml.models import AmlSettings, IdentityCheck, PolicyDocument, RiskQuestion, TrainingRecord
from apps.aml.tests.test_risk import answers_post, submitted
from apps.clients.tests.factories import ClientFactory, ContactFactory
from apps.events.models import ActivityEvent
from apps.jobs.registry import REGISTRY
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def approved_client(level="low", status="active"):
    a = submitted(ClientFactory(status=status), level=level)
    return services.approve(owner(), a)


def test_register_lists_clients_with_level_state_and_dates(client):
    a = approved_client("high")
    ClientFactory(name="No Record Ltd", status="active")
    sign_in(client, staff())
    page = client.get(reverse("aml:register"))
    assert page.status_code == 200
    body = page.content.decode()
    assert a.client.name in body and "No Record Ltd" in body
    only_high = client.get(reverse("aml:register") + "?level=high").content.decode()
    assert a.client.name in only_high and "No Record Ltd" not in only_high
    imported = client.get(reverse("aml:register") + "?state=needs_review").content.decode()
    assert "No Record Ltd" in imported and a.client.name not in imported


def test_register_export_is_logged_and_needs_the_export_right(client):
    approved_client()
    url = reverse("aml:register_export")
    assert client.get(url).status_code == 302
    sign_in(client, staff())
    assert client.get(url).status_code == 403
    sign_in(client, owner())
    response = client.get(url)
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    assert b"Client,Reference" in response.content
    assert ActivityEvent.objects.filter(
        verb="export.run", summary__contains="AML register"
    ).exists()


def test_register_export_blocks_spreadsheet_formulas(client):
    approved_client()
    ClientFactory(name="=HYPERLINK(1)", status="active")
    sign_in(client, owner())
    assert b"'=HYPERLINK" in client.get(reverse("aml:register_export")).content


def test_review_task_is_made_thirty_days_before_and_only_once():
    a = approved_client()
    assert jobs.create_review_tasks() == 0  # three years away
    a.next_review_due = timezone.localdate() + timedelta(days=29)
    a.save()
    assert jobs.create_review_tasks() == 1
    task = Task.objects.get(title=f"AML review: {a.client.name}")
    assert task.category.name == "AML" and task.client == a.client
    assert jobs.create_review_tasks() == 0


def test_expiry_notice_sixty_days_before_once():
    a = approved_client()
    contact = ContactFactory()
    check = IdentityCheck.objects.create(
        client=a.client,
        contact=contact,
        state="verified",
        document_expiry=timezone.localdate() + timedelta(days=59),
    )
    assert jobs.notify_expiring_documents() == 1
    assert jobs.notify_expiring_documents() == 0
    check.refresh_from_db()
    assert check.state == "verified"  # the check does not lapse by itself


def test_the_job_is_registered():
    assert "aml_reviews" in REGISTRY


# ---------------------------------------------------------------- settings


def test_settings_pages_need_the_settings_right(client):
    urls = [
        reverse("aml:questions"),
        reverse("aml:bands"),
        reverse("aml:records"),
    ]
    for url in urls:
        assert client.get(url).status_code == 302
    sign_in(client, staff())
    for url in urls:
        assert client.get(url).status_code == 403
    sign_in(client, manager())
    for url in urls:
        assert client.get(url).status_code == 200


def test_score_bands_and_review_intervals_are_settings(client):
    sign_in(client, manager())
    response = client.post(
        reverse("aml:bands"),
        {
            "medium_from": 3,
            "high_from": 8,
            "review_months_high": 6,
            "review_months_medium": 12,
            "review_months_low": 24,
        },
    )
    assert response.status_code == 302
    settings_row = AmlSettings.load()
    assert settings_row.level_for(3) == "medium" and settings_row.level_for(8) == "high"
    assert settings_row.review_months("high") == 6
    bad = client.post(
        reverse("aml:bands"),
        {
            **{
                "medium_from": 8,
                "high_from": 5,
                "review_months_high": 1,
                "review_months_medium": 1,
                "review_months_low": 1,
            }
        },
    )
    assert bad.status_code == 422


def test_records_training_and_policy_documents(client):
    boss = manager()
    sign_in(client, boss)
    assert (
        client.post(
            reverse("aml:records"),
            {"supervisory_body": "Example Body", "nominated_officer": boss.pk},
        ).status_code
        == 302
    )
    row = AmlSettings.load()
    assert row.supervisory_body == "Example Body" and row.nominated_officer == boss
    client.post(
        reverse("aml:training_add"),
        {"person": boss.pk, "trained_on": "2025-09-01", "course": "AML basics", "notes": ""},
    )
    assert TrainingRecord.objects.count() == 1
    page = client.get(reverse("aml:records")).content.decode()
    assert "Training is due again" in page  # more than eleven months ago
    pdf = SimpleUploadedFile("policy.pdf", b"%PDF-1.4 made up", content_type="application/pdf")
    client.post(reverse("aml:policy_add"), {"title": "Our AML policy", "file": pdf})
    doc = PolicyDocument.objects.get()
    # Served through a permission-checked view; signed-out users are sent to sign in.
    url = reverse("aml:policy", args=[doc.pk])
    assert client.get(url).status_code == 200
    client.logout()
    assert client.get(url).status_code == 302


def test_questions_can_be_added_switched_off_and_the_active_ones_are_asked(client):
    sign_in(client, manager())
    response = client.post(
        reverse("aml:question_add"),
        {
            "section": "The client",
            "text": "Is the client new to the UK?",
            "answer_type": "choice",
            "yes_score": 0,
            "no_score": 0,
            "choices": "Less than a year | 2\nOver a year | 0",
            "position": 5,
            "active": "on",
        },
    )
    assert response.status_code == 302
    question = RiskQuestion.objects.get(text="Is the client new to the UK?")
    assert [o["score"] for o in question.options] == [2, 0]
    client.post(reverse("aml:question_toggle", args=[question.pk]))
    question.refresh_from_db()
    assert question.active is False
    a = services.start_assessment(manager(), ClientFactory())
    services.apply_form(a, answers_post())
    assert str(question.pk) not in a.answers
