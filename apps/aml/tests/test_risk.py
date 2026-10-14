from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, sign_in, staff
from apps.aml import services
from apps.aml.models import AmlSettings, RiskAssessment, RiskQuestion
from apps.clients import services as client_services
from apps.clients.tests.factories import ClientFactory
from apps.companieshouse.models import CompanySnapshot
from apps.events.models import ActivityEvent

pytestmark = pytest.mark.django_db


def q(text_start: str) -> RiskQuestion:
    return RiskQuestion.objects.get(text__startswith=text_start)


def answers_post(overrides=None, **extra):
    """A form post answering every question with the safe answer, unless overridden."""
    data = {}
    for question in RiskQuestion.objects.filter(active=True):
        safe = next(o for o in question.options if o["score"] == 0)
        data[f"q_{question.pk}"] = safe["value"]
        if question.records_check:
            data[f"d_{question.pk}"] = "2026-10-14"
            data[f"h_{question.pk}"] = "Online search"
    for question, value in (overrides or {}).items():
        data[f"q_{question.pk}"] = value
    data.update(extra)
    return data


def draft(client=None, user=None):
    client = client or ClientFactory()
    return services.start_assessment(user or manager(), client)


def test_the_seed_questions_match_the_spec():
    questions = list(RiskQuestion.objects.all())
    assert len(questions) == 17
    assert {x.section for x in questions} == {
        "The client",
        "Ownership",
        "Geography",
        "The business",
        "People",
        "Our service",
    }
    sanctions = q("Did a check against the UK sanctions list")
    assert sanctions.option("yes") == {
        "value": "yes",
        "label": "Yes",
        "score": 10,
        "enhanced": True,
    }
    assert "speak to the owner" in sanctions.help_text and sanctions.records_check
    pep = q("Is the client, an owner or a close relative")
    assert pep.records_check and pep.option("yes")["enhanced"]
    assert q("Have we met the client").option("no")["score"] == 2
    assert q("Have all owners with more than 25%").option("no") == {
        "value": "no",
        "label": "No",
        "score": 5,
        "enhanced": True,
    }


@pytest.mark.parametrize(
    ("score", "level"), [(0, "low"), (4, "low"), (5, "medium"), (9, "medium"), (10, "high")]
)
def test_score_bands(score, level):
    assert AmlSettings.load().level_for(score) == level


def test_scoring_low_medium_high_and_enhanced():
    a = draft()
    services.apply_form(a, answers_post())
    assert (a.score, a.suggested_level, a.enhanced_needed) == (0, "low", False)
    services.apply_form(
        a,
        answers_post(
            {q("Is the business in a higher-risk"): "yes", q("Does the business handle"): "yes"}
        ),
    )
    assert (a.score, a.suggested_level) == (6, "medium")
    services.apply_form(
        a,
        answers_post(
            {
                q("Will we hold"): "yes",
                q("Does the business handle"): "yes",
                q("Is the ownership"): "yes",
                q("Does the work involve"): "yes",
            }
        ),
    )
    assert (a.score, a.suggested_level) == (12, "high")
    # An enhanced answer makes it high whatever the score.
    services.apply_form(a, answers_post({q("Is the client acting on behalf"): "yes"}))
    assert a.score == 5 and a.enhanced_needed and a.suggested_level == "high"


def test_a_lower_level_than_suggested_needs_a_reason():
    a = draft()
    post = answers_post(
        {
            q("Will we hold"): "yes",
            q("Does the business handle"): "yes",
            q("Is the ownership"): "yes",
            q("Does the work involve"): "yes",
        },
        level="medium",
    )
    problems = services.save_draft(manager(), a, post, submit=True)
    assert any("lower level" in p for p in problems)
    post["level_reason"] = "Long-standing family business, known to the partner."
    assert services.save_draft(manager(), a, post, submit=True) == []
    a.refresh_from_db()
    assert a.state == "submitted" and a.level == "medium"


def test_a_higher_level_than_suggested_needs_no_reason():
    a = draft()
    assert services.save_draft(manager(), a, answers_post(level="high"), submit=True) == []


def test_enhanced_answers_need_notes_and_the_check_date_is_recorded():
    a = draft()
    sanctions = q("Did a check against the UK sanctions list")
    post = answers_post({sanctions: "yes"})
    post[f"d_{sanctions.pk}"] = ""
    problems = services.save_draft(manager(), a, post, submit=True)
    assert any("Enhanced checks are needed" in p for p in problems)
    assert any("date checked" in p for p in problems)
    post.update(
        enhanced_notes="Owner spoke to the client and reviewed funds.",
        **{f"d_{sanctions.pk}": "2026-10-14", f"h_{sanctions.pk}": "Gov.uk sanctions list"},
    )
    assert services.save_draft(manager(), a, post, submit=True) == []
    a.refresh_from_db()
    assert a.level == "high"


def test_every_question_must_be_answered_to_submit():
    a = draft()
    post = answers_post()
    del post[f"q_{q('Will we hold').pk}"]
    problems = services.save_draft(manager(), a, post, submit=True)
    assert any("Will we hold" in p for p in problems)
    a.refresh_from_db()
    assert a.state == "draft"


def submitted(client=None, level="low", assessor=None, **extra):
    assessor = assessor or manager()
    a = draft(client, assessor)
    post = answers_post(level=level, **extra)
    assert services.save_draft(assessor, a, post, submit=True) == []
    a.refresh_from_db()
    return a


def test_approval_needs_the_right():
    a = submitted()
    with pytest.raises(PermissionDenied):
        services.approve(staff(), a)


def test_approval_sets_review_date_by_level_and_ticks_the_checklist():
    client = ClientFactory(status="prospect")
    client_services.change_status(manager(), client, "onboarding")
    for level, months in (("low", 36), ("medium", 24), ("high", 12)):
        a = submitted(client, level=level, assessor=manager())
        approver = owner()
        done = services.approve(approver, a)
        expected = date(timezone.localdate().year + months // 12, timezone.localdate().month, 1)
        assert done.next_review_due.year == expected.year
        assert done.state == "approved" and done.approved_by == approver
        client.risk_assessments.filter(state="approved")
        # Start the next review to loop.
        if level != "high":
            services.start_assessment(manager(), client, "test")
    assert client.onboarding_items.get(key="risk_assessment_approved").state == "done"
    assert client.risk_assessments.filter(state="approved").count() == 1  # others superseded


def test_assessor_cannot_approve_own_high_risk_assessment_when_another_approver_exists():
    assessor = owner(email="boss@example.com")
    owner(email="second@example.com")
    a = submitted(level="high", assessor=assessor)
    with pytest.raises(ValidationError, match="someone other than its assessor"):
        services.approve(assessor, a)
    services.approve(User_other(), a)


def User_other():
    return owner(email="third@example.com")


def test_sole_approver_may_approve_own_high_risk_assessment():
    assessor = owner()
    a = submitted(level="high", assessor=assessor)
    services.approve(assessor, a)
    a.refresh_from_db()
    assert a.state == "approved"


def test_low_risk_assessor_may_approve_own_assessment():
    assessor = owner()
    owner()
    a = submitted(level="low", assessor=assessor)
    services.approve(assessor, a)


def test_send_back_needs_a_reason_and_lets_the_assessor_edit_again():
    assessor = manager()
    a = submitted(assessor=assessor)
    boss = owner()
    with pytest.raises(ValidationError):
        services.send_back(boss, a, " ")
    services.send_back(boss, a, "Check the ownership answer.")
    a.refresh_from_db()
    assert a.state == "sent_back" and a.is_editable
    assert services.save_draft(assessor, a, answers_post(level="low"), submit=True) == []


def test_approval_saves_a_companies_house_snapshot_to_documents():
    client = ClientFactory(company_number="00000000")
    CompanySnapshot.objects.create(
        client=client,
        company_number="00000000",
        profile={"company_status": "active", "date_of_creation": "2020-01-01"},
        officers=[
            {"name": "SAMPLE, Sam", "officer_role": "director", "appointed_on": "2020-01-01"}
        ],
        owners=[
            {"name": "Sam Sample", "natures_of_control": ["ownership-of-shares-75-to-100-percent"]}
        ],
        synced_at=timezone.now(),
    )
    a = submitted(client)
    services.approve(owner(), a)
    a.refresh_from_db()
    assert a.ch_snapshot_document is not None
    assert client.documents.filter(title__startswith="Companies House record").exists()


def test_a_changed_question_is_logged(client):
    sign_in(client, manager())
    question = q("Does the business handle")
    response = client.post(
        reverse("aml:question_edit", args=[question.pk]),
        {
            "section": question.section,
            "text": question.text,
            "answer_type": "yes_no",
            "yes_score": 6,
            "no_score": 0,
            "enhanced_on": "",
            "position": question.position,
            "active": "on",
        },
    )
    assert response.status_code == 302
    question.refresh_from_db()
    assert question.option("yes")["score"] == 6
    event = ActivityEvent.objects.filter(verb="setting.changed").first()
    assert "risk question" in event.summary


# ---------------------------------------------------------------- state


def test_aml_state_is_worked_out():
    today = timezone.localdate()
    client = ClientFactory(status="prospect")
    assert services.state_of(client)[0] == "not_started"
    live_without_record = ClientFactory(status="active")
    assert services.state_of(live_without_record)[0] == "needs_review"
    a = draft(client)
    assert services.state_of(client)[0] == "in_progress"
    a = submitted(ClientFactory(status="onboarding"))
    assert services.state_of(a.client)[0] == "awaiting_approval"
    a = services.approve(owner(), a)
    assert services.state_of(a.client)[0] == "approved"
    a.next_review_due = today + timedelta(days=10)
    a.save()
    assert services.state_of(a.client)[0] == "review_due"
    a.next_review_due = today - timedelta(days=1)
    a.save()
    assert services.state_of(a.client)[0] == "review_overdue"


def test_a_review_starts_from_the_previous_answers():
    a = submitted(level="low", **{})
    services.approve(owner(), a)
    review = services.start_assessment(manager(), a.client, "Annual review")
    assert review.version == 2 and review.answers == a.answers and review.state == "draft"
    # Only one open at a time.
    assert services.start_assessment(manager(), a.client).pk == review.pk


def test_prompts_for_ownership_change_reactivation_and_higher_risk_service():
    from apps.companieshouse.services import SyncResult, client_synced
    from apps.services import services as svc
    from apps.services.models import Service

    a = submitted(ClientFactory(status="active", client_type="ltd"))
    services.approve(owner(), a)
    client = a.client
    client_synced.send(sender=type(client), client=client, result=SyncResult(people_changed=True))
    assert client.aml_review_prompts.filter(reason__contains="director or owner").exists()
    risky = Service.objects.filter(applies_to__contains=["ltd"]).first()
    AmlSettings.load().higher_risk_services.add(risky)
    svc.switch_on(manager(), client, risky)
    assert client.aml_review_prompts.filter(reason__startswith="Higher-risk service").exists()
    client_services.set_status(manager(), client, "former")
    client_services.set_status(manager(), client, "active")
    assert client.aml_review_prompts.filter(reason="The client was reactivated.").exists()
    # Starting the review clears the prompts.
    services.start_assessment(manager(), client)
    assert not services.open_prompts(client).exists()


# ---------------------------------------------------------------- pages


def test_risk_pages_need_sign_in_and_assessments_use_the_right_client(client):
    a = submitted()
    for name, args in [
        ("aml:tab", [a.client_id]),
        ("aml:assessment", [a.client_id, a.pk]),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 302
    sign_in(client, staff())
    assert client.get(reverse("aml:tab", args=[a.client_id])).status_code == 200
    other = ClientFactory()
    assert client.get(reverse("aml:assessment", args=[other.pk, a.pk])).status_code == 404
    assert client.post(reverse("aml:approve", args=[a.client_id, a.pk])).status_code == 403


def test_assessment_form_saves_and_submits_through_the_page(client):
    c = ClientFactory(status="onboarding")
    sign_in(client, manager())
    client.post(reverse("aml:start", args=[c.pk]))
    a = RiskAssessment.objects.get(client=c)
    page = client.get(reverse("aml:assessment", args=[c.pk, a.pk]))
    assert page.status_code == 200 and b"Have we met the client" in page.content
    response = client.post(
        reverse("aml:assessment", args=[c.pk, a.pk]), {**answers_post(), "submit": "1"}
    )
    assert response.status_code == 302
    a.refresh_from_db()
    assert a.state == "submitted"
    incomplete = client.post(reverse("aml:assessment", args=[c.pk, a.pk]), {})
    assert incomplete.status_code == 403  # no longer editable once submitted


def test_header_shows_the_aml_badge(client):
    c = ClientFactory()
    sign_in(client, staff())
    assert b"AML:" in client.get(reverse("clients:detail", args=[c.pk])).content
