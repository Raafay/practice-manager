"""Reports: access, each report's filters, the shared export, and the client summary PDF."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import manager, owner, portal_user, sign_in, staff
from apps.clients.tests.factories import ClientFactory
from apps.comms.models import QueuedMessage
from apps.comms.tests.factories import make_template, queued
from apps.events.models import ActivityEvent
from apps.pipeline.tests.helpers import no_fee_staff, prospect
from apps.portal import requests as request_services
from apps.portal.models import Request
from apps.reports import summary
from apps.reports.catalogue import REPORTS
from apps.services.tests.factories import take
from apps.tasks import services as task_services
from apps.tasks.tests.factories import make_task
from apps.timekeeping import services as time_services

pytestmark = pytest.mark.django_db

UTR = "1111111111"


def build(key, user, **params):
    report = REPORTS[key]
    form = report.form(params or None, user)
    data = form.data_or_empty if form.is_bound else {}
    return report.build(data, user)


def texts(result, column=0):
    return [str(row[column]) for row in result.rows]


# ---------------------------------------------------------------- access


def addresses(client_pk):
    names = [("reports:index", [])]
    for key in REPORTS:
        names += [(f"reports:{key}", []), (f"reports:{key}_export", [])]
    return [*names, ("reports:client_summary", [client_pk])]


def test_signed_out_users_are_sent_to_sign_in(client):
    c = ClientFactory()
    for name, args in addresses(c.pk):
        assert "/login/" in client.get(reverse(name, args=args))["Location"], name


def test_a_portal_user_gets_403(client):
    c = ClientFactory()
    sign_in(client, portal_user())
    for name, args in addresses(c.pk):
        assert client.get(reverse(name, args=args)).status_code == 403, name


def test_every_report_opens_for_staff_and_export_needs_data_export(client):
    sign_in(client, staff())
    assert client.get(reverse("reports:index")).status_code == 200
    for key in REPORTS:
        page = client.get(reverse(f"reports:{key}"))
        assert page.status_code == 200, key
        assert "Export CSV" not in page.content.decode()
        assert client.get(reverse(f"reports:{key}_export")).status_code == 403, key


def test_the_reports_page_lists_every_report_old_and_new(client):
    sign_in(client, manager())
    page = client.get(reverse("reports:index")).content.decode()
    for title in ("Deadlines", "Client list", "AML register", "Tasks", "Services", "Time"):
        assert title in page
    for title in ("Requests", "Pipeline", "Communications"):
        assert title in page


def test_export_is_logged_and_made_safe(client):
    boss = owner()
    make_task(boss, title="=SUM(A1:A2)", client=ClientFactory())
    sign_in(client, boss)
    response = client.get(reverse("reports:tasks_export"))
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/csv")
    assert body.splitlines()[0].startswith("Task,Client,Kind")
    assert "'=SUM(A1:A2)" in body
    event = ActivityEvent.objects.get(verb="export.run")
    assert event.data["list"] == "tasks" and event.data["rows"] == 1


# ---------------------------------------------------------------- filters


def test_tasks_report_filters():
    boss = owner()
    a, b = staff(name="Ash Sample"), staff(name="Bea Sample")
    c = ClientFactory(name="Filter Client Ltd")
    first = make_task(boss, title="First", owner=a, client=c, due_date=date(2026, 11, 1))
    make_task(boss, title="Second", owner=b, kind="internal", due_date=date(2026, 12, 1))
    done = make_task(boss, title="Done one", owner=a)
    task_services.complete(boss, done)
    assert texts(build("tasks", boss)) == ["First", "Second"]
    assert texts(build("tasks", boss, owner=str(a.pk))) == ["First"]
    assert texts(build("tasks", boss, kind="internal")) == ["Second"]
    assert texts(build("tasks", boss, client="filter client")) == ["First"]
    assert texts(build("tasks", boss, due_to="2026-11-15")) == ["First"]
    today = timezone.localdate().isoformat()
    assert texts(build("tasks", boss, state="done", done_from=today)) == ["Done one"]
    assert texts(build("tasks", boss, state="done", done_to="2020-01-01")) == []
    assert first.pk


def test_services_report_filters_and_fees_need_the_right():
    boss = owner()
    c1 = ClientFactory(name="Alpha Example Ltd", company_utr=UTR)
    c2 = ClientFactory(name="Beta Example Ltd", status="paused")
    take(c1, "accounts", fee_amount=Decimal("100.00"))
    take(c2, "vat", fee_amount=Decimal("300.00"), fee_frequency="quarterly")
    take(c2, "payroll", fee_amount=None, state="ended")
    result = build("services", boss)
    assert texts(result) == ["Alpha Example Ltd", "Beta Example Ltd"]
    assert "Fee" in [c.label for c in result.columns]
    assert ("Monthly total", "£200.00") in result.figures
    accounts = c1.client_services.get().service_id
    assert texts(build("services", boss, service=str(accounts))) == ["Alpha Example Ltd"]
    assert texts(build("services", boss, status="paused")) == ["Beta Example Ltd"]
    assert len(build("services", boss, state="all").rows) == 3
    plain = no_fee_staff()
    hidden = build("services", plain)
    assert "Fee" not in [c.label for c in hidden.columns]
    assert all(label != "Monthly total" for label, _v in hidden.figures)
    assert all(Decimal("100.00") not in row for row in hidden.rows)
    # A manager sees each client's fee but not the practice-wide total.
    shown = build("services", manager())
    assert "Fee" in [c.label for c in shown.columns]
    assert all(label != "Monthly total" for label, _v in shown.figures)


def test_time_report_groups_and_dates():
    a, b = staff(name="Ash Sample"), staff(name="Bea Sample")
    c = ClientFactory(name="Time Client Ltd")
    today = timezone.localdate()
    time_services.log_time(a, minutes=90, client=c, on_date=today)
    time_services.log_time(b, minutes=30, client=c, on_date=today)
    time_services.log_time(a, minutes=60, on_date=today - timedelta(days=400))
    by_client = build("time", a)
    assert by_client.rows == [["Time Client Ltd", Decimal("2.00"), Decimal("2.00"), 2]]
    by_person = build("time", a, group="person")
    assert [r[:2] for r in by_person.rows] == [
        ["Ash Sample", Decimal("1.50")],
        ["Bea Sample", Decimal("0.50")],
    ]
    old = build("time", a, group="month", start="2000-01-01", person=str(a.pk))
    assert len(old.rows) == 2
    assert old.rows[-1][0] == today.strftime("%m/%Y")


def test_requests_report_volume_and_times():
    boss = owner()
    c = ClientFactory(name="Request Client Ltd")
    received = timezone.now() - timedelta(hours=10)
    r1 = Request.objects.create(client=c, channel="form", subject="One")
    r2 = Request.objects.create(client=c, channel="phone", subject="Two")
    Request.objects.create(channel="form", subject="Junk", state="spam")
    Request.objects.filter(pk__in=[r1.pk, r2.pk]).update(received_at=received)
    r1.refresh_from_db()
    request_services.close(boss, r1, "Sorted.")
    result = build("requests", boss)
    rows = {r[0]: r for r in result.rows}
    assert rows["Request link"][1:5] == [1, 0, 1, 1]  # one real, closed; one spam
    assert rows["Request link"][5] == pytest.approx(Decimal("10.0"), abs=Decimal("0.2"))
    assert rows["Phone"][1:5] == [1, 1, 0, 0] and rows["Phone"][5] is None
    by_client = build("requests", boss, group="client", channel="phone")
    assert [r[0] for r in by_client.rows] == ["Request Client Ltd"]


def test_pipeline_report_by_stage_source_and_outcome():
    boss = owner()
    prospect("Open One Ltd", stage_key="enquiry", source="website")
    prospect("Won One Ltd", stage_key="won", source="website")
    lost = prospect("Lost One Ltd", stage_key="lost", source="word_of_mouth")
    lost.prospect.lost_reason = "price"
    lost.prospect.save()
    result = build("pipeline", boss)
    assert len(result.rows) == 3
    assert ("Won", 1) in result.figures and ("Lost", 1) in result.figures
    sections = {s.title: s.rows for s in result.sections}
    assert ["Website", 2, 1, 0] in sections["By source"]
    assert sections["Lost reasons"] == [["Price", 1]]
    assert texts(build("pipeline", boss, outcome="won")) == ["Won One Ltd"]
    assert texts(build("pipeline", boss, source="word_of_mouth")) == ["Lost One Ltd"]


def test_communications_report_by_template():
    boss = owner()
    c = ClientFactory()
    template = make_template(name="VAT reminder")
    sent = queued(c, boss, template=template)
    QueuedMessage.objects.filter(pk=sent.pk).update(state="sent", delivery_state="bounced")
    failed = queued(c, boss, template=template)
    QueuedMessage.objects.filter(pk=failed.pk).update(state="failed")
    queued(c, boss)
    result = build("communications", boss)
    rows = {r[0]: r for r in result.rows}
    assert rows["VAT reminder"][1:5] == [1, 0, 1, 1]
    assert rows["Written by hand"][5] == 1
    assert build("communications", boss, end="2000-01-01").rows == []


# ---------------------------------------------------------------- exports and secrets


def test_every_export_respects_fees_view_and_leaves_out_encrypted_values(client):
    c = ClientFactory(name="Secret Example Ltd", company_utr=UTR, ch_auth_code="ABC123")
    take(c, "accounts", fee_amount=Decimal("123.45"))
    make_task(owner(), title="A task", client=c)
    person = no_fee_staff()
    person.extra_rights = ["data.export"]
    person.save()
    sign_in(client, person)
    bodies = [client.get(reverse(f"reports:{key}_export")).content.decode() for key in REPORTS]
    bodies.append(
        client.get(
            reverse("clients:export"), {"cols": ["name", "monthly_fee", "reference"]}
        ).content.decode()
    )
    bodies.append(client.get(reverse("services:report_deadlines_export")).content.decode())
    bodies.append(client.get(reverse("aml:register_export")).content.decode())
    for body in bodies:
        assert UTR not in body and "ABC123" not in body
        assert "123.45" not in body
    assert "Secret Example Ltd" in bodies[1]  # the services export ran


# ---------------------------------------------------------------- client summary


def test_the_client_summary_pdf_downloads_and_is_logged(client):
    c = ClientFactory(name="Summary Example Ltd")
    sign_in(client, staff())
    response = client.get(reverse("reports:client_summary", args=[c.pk]))
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"
    assert ActivityEvent.objects.filter(verb="report.client_summary", client=c).exists()
    page = client.get(reverse("clients:detail", args=[c.pk])).content.decode()
    assert "Generate report" in page


def test_the_summary_hides_fees_without_the_right_and_never_shows_tax_references():
    from django.template.loader import render_to_string

    c = ClientFactory(name="Summary Example Ltd", company_utr=UTR)
    take(c, "accounts", fee_amount=Decimal("987.65"))
    make_task(owner(), title="Prepare the accounts", client=c)
    with_fees = render_to_string("reports/client_summary_pdf.html", summary.context(c, manager()))
    assert "987.65" in with_fees and "Prepare the accounts" in with_fees
    plain = summary.context(c, no_fee_staff())
    without = render_to_string("reports/client_summary_pdf.html", plain)
    assert "987.65" not in without and "Monthly total" not in without
    assert UTR not in with_fees and UTR not in without
