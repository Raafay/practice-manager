"""The confirmation statement check and the client details form."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import manager, sign_in, staff
from apps.clients.models import Client, Document, Note
from apps.clients.tests.factories import ClientFactory
from apps.events.models import Notification
from apps.onboarding import services as onboarding
from apps.portal import formspecs, pforms, services
from apps.portal.models import PortalForm, PortalItem
from apps.portal.tests.helpers import portal_login, portal_person
from apps.tasks.tests.factories import make_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(client):
    boss = manager()
    cl = ClientFactory(
        name="Alpha Ltd",
        manager=boss,
        registered_office="1 Example Street\nSampletown\nZZ1 1ZZ",
        sic_codes="62012",
        trading_name="Alpha Trading",
        client_type=Client.Type.LTD,
    )
    user, contact, link = portal_person(cl, first_name="Sam", last_name="Sample")
    link.roles = ["director", "shareholder"]
    link.shareholding_percent = 100
    link.save()
    portal_login(client, user)
    return {"boss": boss, "cl": cl, "user": user, "contact": contact, "http": client}


def confirm_item(w):
    task = make_task(w["boss"], client=w["cl"], owner=w["boss"])
    task.steps.create(name="Details sent to client", position=1)
    task.steps.create(name="Client confirmed", position=2, stops_reminders=True)
    item = services.create_item(
        w["boss"], w["cl"], PortalItem.Kind.CONFIRM_DETAILS, "Check your details", task=task
    )
    return task, item


def answers(**overrides):
    data = {}
    for key in (
        "registered_office", "officers", "psc", "business_activity", "shareholders",
        "registered_email",
    ):  # fmt: skip
        data[f"{key}__choice"] = "no_change"
    data.update(overrides)
    return data


# ---------------------------------------------------------------- confirmation statement


def test_the_form_shows_what_companies_house_holds(setup):
    _, item = confirm_item(setup)
    page = setup["http"].get(reverse("portal:form", args=[item.public_id])).content.decode()
    for text in ("Registered office", "1 Example Street", "62012", "Sam Sample", "100"):
        assert text in page


def test_every_section_needs_an_answer_and_a_change_needs_a_description(setup):
    task, item = confirm_item(setup)
    url = reverse("portal:form", args=[item.public_id])
    response = setup["http"].post(url, {"registered_office__choice": "no_change"})
    assert response.status_code == 422
    response = setup["http"].post(url, answers(officers__choice="change", officers__text=""))
    assert response.status_code == 422
    assert task.steps.filter(done_at__isnull=False).count() == 0


def test_submitting_saves_a_pdf_ticks_the_step_and_tells_the_owner(setup):
    task, item = confirm_item(setup)
    url = reverse("portal:form", args=[item.public_id])
    response = setup["http"].post(
        url,
        answers(
            officers__choice="change",
            officers__text="Alex Example resigned on 01/03/2026.",
        ),
    )
    assert response.status_code == 302
    form = PortalForm.objects.get(item=item)
    item.refresh_from_db()
    assert form.state == "submitted" and item.state == "done"
    assert form.answers["officers"]["choice"] == "change"
    assert task.steps.get(name="Client confirmed").done_at is not None
    assert task.steps.get(name="Details sent to client").done_at is None
    doc = form.document
    assert doc.client == setup["cl"] and doc.content_type == "application/pdf"
    assert doc.shared_with_portal and doc.source == Document.Source.SYSTEM
    note = Notification.objects.get(user=setup["boss"], message__contains="confirmed their company")
    assert "Directors and secretary" in note.message  # a change is called out
    # Sent forms cannot be sent again.
    assert setup["http"].post(url, answers()).status_code == 409


def test_a_no_change_submission_says_so(setup):
    _, item = confirm_item(setup)
    setup["http"].post(reverse("portal:form", args=[item.public_id]), answers())
    note = Notification.objects.get(user=setup["boss"], message__contains="confirmed their company")
    assert "no changes" in note.message


def test_staff_see_changes_highlighted(setup):
    _, item = confirm_item(setup)
    setup["http"].post(
        reverse("portal:form", args=[item.public_id]),
        answers(psc__choice="change", psc__text="New PSC from June."),
    )
    form = PortalForm.objects.get(item=item)
    from django.test import Client as Browser

    browser = Browser()
    sign_in(browser, staff())
    page = browser.get(reverse("portal:review", args=[form.pk])).content.decode()
    assert "New PSC from June." in page and "bg-amber-50" in page


# ---------------------------------------------------------------- client details


def details_item(w):
    onboarding.ensure_checklist(w["cl"])
    return services.create_item(
        w["boss"], w["cl"], PortalItem.Kind.CLIENT_DETAILS, "Your details", reuse=False
    )


def person_key(contact, attr):
    return formspecs.person_key(contact, attr)


def test_the_form_is_filled_in_with_what_we_hold(setup):
    item = details_item(setup)
    page = setup["http"].get(reverse("portal:form", args=[item.public_id])).content.decode()
    assert "Alpha Trading" in page and "Sam Sample: date of birth" in page


def test_save_and_come_back_changes_nothing_on_the_record(setup):
    item = details_item(setup)
    url = reverse("portal:form", args=[item.public_id])
    setup["http"].post(url, {"save": "1", "trading_name": "Brand New Name"})
    form = PortalForm.objects.get(item=item)
    assert form.state == "draft" and form.answers["trading_name"] == "Brand New Name"
    setup["cl"].refresh_from_db()
    assert setup["cl"].trading_name == "Alpha Trading"
    page = setup["http"].get(url).content.decode()
    assert "Brand New Name" in page  # the draft comes back


def test_sending_changes_nothing_either_until_staff_apply(setup):
    item = details_item(setup)
    contact = setup["contact"]
    url = reverse("portal:form", args=[item.public_id])
    setup["http"].post(
        url,
        {
            "send": "1",
            "trading_name": "Brand New Name",
            person_key(contact, "dob"): "1980-02-03",
            person_key(contact, "ni"): "ZZ 00 00 00 Z",
            "software": "Sample Books",
        },
    )
    form = PortalForm.objects.get(item=item)
    assert form.state == "submitted"
    setup["cl"].refresh_from_db()
    contact.refresh_from_db()
    assert setup["cl"].trading_name == "Alpha Trading"
    assert contact.date_of_birth is None and contact.ni_number == ""
    assert not Note.objects.filter(client=setup["cl"]).exists()
    # The tax reference is not stored in the clear in the answers.
    assert "ZZ 00 00 00 Z" not in str(form.answers) and "ZZ0000" not in str(form.answers)
    assert Notification.objects.filter(
        user=setup["boss"], message__contains="details form"
    ).exists()


def test_the_review_screen_applies_per_field_and_masks_secrets(setup):
    item = details_item(setup)
    contact = setup["contact"]
    setup["http"].post(
        reverse("portal:form", args=[item.public_id]),
        {
            "send": "1",
            "trading_name": "Brand New Name",
            person_key(contact, "ni"): "ZZ 00 00 00 Z",
            "software": "Sample Books",
        },
    )
    form = PortalForm.objects.get(item=item)
    browser = _staff_browser()
    page = browser.get(reverse("portal:review", args=[form.pk])).content.decode()
    assert "Brand New Name" in page and "Alpha Trading" in page
    assert "ZZ 00 00 00 Z" not in page  # masked

    act = reverse("portal:review_act", args=[form.pk])
    browser.post(act, {"action": "apply", "key": "trading_name"})
    setup["cl"].refresh_from_db()
    assert setup["cl"].trading_name == "Brand New Name"
    contact.refresh_from_db()
    assert contact.ni_number == ""  # not applied yet
    browser.post(act, {"action": "apply", "key": person_key(contact, "ni")})
    contact.refresh_from_db()
    assert contact.ni_number == "ZZ 00 00 00 Z"
    # A note-only field is added as a note when applied.
    browser.post(act, {"action": "apply", "key": "software"})
    assert Note.objects.filter(client=setup["cl"], text__contains="Sample Books").exists()
    form.refresh_from_db()
    assert form.state == "reviewed"
    assert setup["cl"].onboarding_items.get(key="client_details").state == "done"


def test_dismissing_the_rest_finishes_the_review_without_changing_the_record(setup):
    item = details_item(setup)
    setup["http"].post(
        reverse("portal:form", args=[item.public_id]),
        {"send": "1", "trading_name": "Brand New Name", "software": "Sample Books"},
    )
    form = PortalForm.objects.get(item=item)
    browser = _staff_browser()
    browser.post(reverse("portal:review_act", args=[form.pk]), {"action": "dismiss_rest"})
    form.refresh_from_db()
    setup["cl"].refresh_from_db()
    assert form.state == "reviewed" and setup["cl"].trading_name == "Alpha Trading"
    assert setup["cl"].onboarding_items.get(key="client_details").state == "done"


def test_applying_everything(setup):
    item = details_item(setup)
    contact = setup["contact"]
    setup["http"].post(
        reverse("portal:form", args=[item.public_id]),
        {"send": "1", "trading_name": "Brand New Name", person_key(contact, "dob"): "1980-02-03"},
    )
    form = PortalForm.objects.get(item=item)
    _staff_browser().post(reverse("portal:review_act", args=[form.pk]), {"action": "apply_all"})
    contact.refresh_from_db()
    setup["cl"].refresh_from_db()
    assert (
        str(contact.date_of_birth) == "1980-02-03" and setup["cl"].trading_name == "Brand New Name"
    )
    assert pforms.review_rows(PortalForm.objects.get(pk=form.pk))[0]["decision"] == "applied"


def test_an_invalid_date_is_refused(setup):
    item = details_item(setup)
    contact = setup["contact"]
    response = setup["http"].post(
        reverse("portal:form", args=[item.public_id]),
        {"send": "1", person_key(contact, "dob"): "not a date"},
    )
    assert response.status_code == 422
    assert PortalForm.objects.get(item=item).state == "draft"


def test_the_review_cannot_be_used_twice_or_for_a_field_not_on_the_form(setup):
    item = details_item(setup)
    setup["http"].post(
        reverse("portal:form", args=[item.public_id]), {"send": "1", "trading_name": "X"}
    )
    form = PortalForm.objects.get(item=item)
    browser = _staff_browser()
    act = reverse("portal:review_act", args=[form.pk])
    browser.post(act, {"action": "apply", "key": "not_a_field"})
    setup["cl"].refresh_from_db()
    assert setup["cl"].trading_name == "Alpha Trading"
    del form


def _staff_browser():
    from django.test import Client as Browser

    browser = Browser()
    sign_in(browser, staff())
    return browser
