"""Import pages: access, the four steps in a browser, the failures download and undo."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.tests.factories import manager, portal_user, sign_in, staff
from apps.clients.models import Client
from apps.events.models import ActivityEvent
from apps.imports.models import ImportRun, SavedMatching
from apps.imports.tests.helpers import SAMPLES, boss, imported, upload

pytestmark = pytest.mark.django_db


@pytest.fixture
def run():
    return imported(boss(), "clients", "clients_messy.csv")


def addresses(run):
    pk = run.pk
    matching = SavedMatching.objects.create(kind="clients", name="X", header_key="x")
    return [
        ("imports:index", [], "get"),
        ("imports:index", [], "post"),
        ("imports:match", [pk], "get"),
        ("imports:match", [pk], "post"),
        ("imports:check", [pk], "get"),
        ("imports:check", [pk], "post"),
        ("imports:run", [pk], "get"),
        ("imports:failures", [pk], "get"),
        ("imports:undo", [pk], "post"),
        ("imports:fetch", [pk], "post"),
        ("imports:progress", [pk], "get"),
        ("imports:matching_delete", [matching.pk], "post"),
        ("imports:helper", [], "get"),
        ("imports:helper", [], "post"),
    ]


def call(client, name, args, method):
    url = reverse(name, args=args)
    return client.get(url) if method == "get" else client.post(url, {})


def test_signed_out_users_are_sent_to_sign_in(client, run):
    for name, args, method in addresses(run):
        assert "/login/" in call(client, name, args, method)["Location"], name


@pytest.mark.parametrize("make", [manager, staff, portal_user])
def test_an_import_by_a_manager_or_staff_is_refused(client, run, make):
    sign_in(client, make())
    for name, args, method in addresses(run):
        assert call(client, name, args, method).status_code == 403, name
    assert ImportRun.objects.count() == 1


def test_the_settings_card_shows_only_with_the_right(client):
    sign_in(client, manager())
    assert reverse("imports:index") not in client.get(reverse("core:settings")).content.decode()
    sign_in(client, boss())
    assert reverse("imports:index") in client.get(reverse("core:settings")).content.decode()


def test_the_four_steps_in_the_browser(client):
    sign_in(client, boss())
    page = client.get(reverse("imports:index"))
    assert "No imports yet" in page.content.decode()
    raw = (SAMPLES / "clients_messy.csv").read_bytes()
    response = client.post(
        reverse("imports:index"),
        {"kind": "clients", "file": SimpleUploadedFile("clients_messy.csv", raw, "text/csv")},
    )
    run = ImportRun.objects.get()
    assert response["Location"] == reverse("imports:match", args=[run.pk])

    page = client.get(response["Location"]).content.decode()
    assert "Hazel Example Ltd" in page and "semicolons" in page and "UTF-8 (with BOM)" in page
    form = {f"col_{i}": run.mapping[h] for i, h in enumerate(run.headers)}
    form["save_as"] = "Messy clients"
    response = client.post(reverse("imports:match", args=[run.pk]), form)
    assert response["Location"] == reverse("imports:check", args=[run.pk])
    assert SavedMatching.objects.filter(name="Messy clients").exists()

    page = client.get(response["Location"]).content.decode()
    assert "Problems, row by row" in page
    assert "is not a client type we know" in page
    assert Client.objects.count() == 0

    response = client.post(reverse("imports:check", args=[run.pk]))
    assert response["Location"] == reverse("imports:run", args=[run.pk])
    assert Client.objects.count() == 3
    page = client.get(response["Location"]).content.decode()
    assert "Rows not imported" in page and "Fetch from Companies House" in page


def test_matching_errors_are_shown(client):
    sign_in(client, boss())
    run = upload(boss(), "clients", "clients_clean.csv")
    form = {f"col_{i}": "" for i in range(len(run.headers))}
    response = client.post(reverse("imports:match", args=[run.pk]), form)
    assert response.status_code == 422
    assert "every client needs one" in response.content.decode()


def test_a_file_that_is_not_csv_is_refused(client):
    sign_in(client, boss())
    response = client.post(
        reverse("imports:index"),
        {"kind": "clients", "file": SimpleUploadedFile("a.xlsx", b"PK\x03\x04", "application/zip")},
    )
    assert response.status_code == 422 and not ImportRun.objects.exists()


def test_the_failures_file_makes_formulas_safe_and_is_logged(client, run):
    sign_in(client, boss())
    response = client.get(reverse("imports:failures", args=[run.pk]))
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/csv")
    assert "Row,Problem,Ref,Name" in body.splitlines()[0]
    line = next(x for x in body.splitlines() if x.startswith("6,"))
    assert "'=HYPERLINK" in line
    assert ActivityEvent.objects.filter(verb="export.run", data__list="import failures").exists()


def test_undo_from_the_page(client, run):
    sign_in(client, boss())
    response = client.post(reverse("imports:undo", args=[run.pk]))
    assert response.status_code == 302
    assert Client.objects.count() == 0
    run.refresh_from_db()
    assert run.state == "undone"


def test_fetch_progress_polls_while_running(client, run):
    sign_in(client, boss())
    client.post(reverse("imports:fetch", args=[run.pk]))
    run.refresh_from_db()
    assert run.fetch_state == "waiting"
    body = client.get(reverse("imports:progress", args=[run.pk])).content.decode()
    assert 'hx-trigger="every 3s"' in body and "Waiting for the background worker" in body
