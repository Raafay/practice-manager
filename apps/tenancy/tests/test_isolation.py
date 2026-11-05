"""Nothing from practice A can be reached on practice B's address (Stage 14 checks).

Every address in the URL walk is visited by each kind of user signed in at practice
A, with A's real records in the address, but on B's address. Each answer must send
the visitor to sign in or be a 404 (or 405 for the wrong method); a page that anyone
may open must not show anything of A's.
"""

import html

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client
from django.urls import reverse
from django_tenants.utils import schema_context

from apps.accounts.tests.factories import owner, sign_in
from apps.core.tests import test_url_walk as walk

pytestmark = pytest.mark.django_db

B_HOST = "other.testserver"
OPEN_RULES = {"public", "signin", "open"}


def _visit_on_b(http, method, url):
    cache.clear()
    cookies = walk.SimpleCookie(http.cookies)
    with transaction.atomic():
        response = getattr(http, method)(url, HTTP_HOST=B_HOST)
        transaction.set_rollback(True)
    http.cookies = cookies
    connection.set_schema("practice_a")
    return response


def _markers(world, users):
    from apps.core.models import PracticeSettings

    names = [
        PracticeSettings.load().practice_name,
        world.client.name,
        *[user.email for user in users if user is not None],
        *[c.name for c in walk.World().models["Prospect"].order_by("pk")[:3]],
    ]
    found = set()
    for name in names:
        found.update({name, html.escape(name)})
    return {marker for marker in found if len(marker) > 5}


def _shows_a(response, markers):
    body = response.content.decode("utf-8", "replace") if response.content else ""
    location = response.get("Location", "")
    return [marker for marker in markers if marker in body or marker in location]


def test_every_address_signed_in_at_a_is_refused_on_b():
    call_command("seed_demo", verbosity=0)
    world = walk.World()
    clients = walk.make_users()
    from apps.accounts.models import User

    markers = _markers(world, list(User.objects.all()))
    failures = []
    for name, route in sorted(walk.all_patterns().items()):
        rules = walk.EXPECTED[name]
        url = reverse(name, kwargs=walk.fill_kwargs(world, name, route) or None)
        for kind, http in clients.items():
            for method in ("get", "post"):
                response = _visit_on_b(http, method, url)
                status = response.status_code
                where = f"{name} {method.upper()} {url} as {kind}"
                if status >= 500:
                    failures.append(f"{where}: server error {status}")
                    continue
                leaked = _shows_a(response, markers)
                if leaked:
                    failures.append(f"{where}: shows A's {leaked[:2]}")
                    continue
                if rules[method] in OPEN_RULES:
                    continue
                refused = status in (404, 405) or walk.is_sign_in_redirect(response)
                if not refused:
                    failures.append(f"{where}: got {status}, expected sign in or 404")
    assert not failures, "\n".join(failures)


def test_a_signed_in_session_from_a_is_not_signed_in_on_b():
    boss = owner()
    http = Client()
    sign_in(http, boss)
    assert http.get("/").status_code == 200
    response = http.get("/", HTTP_HOST=B_HOST)
    assert walk.is_sign_in_redirect(response)


def test_a_file_uploaded_in_a_cannot_be_opened_from_b_even_by_its_id():
    """B's own owner, signed in at B, asks for A's document by its exact id."""
    from django.core.files.base import ContentFile

    from apps.clients.models import Document
    from apps.clients.tests.factories import ClientFactory

    document = Document.objects.create(
        client=ClientFactory(),
        file=ContentFile(b"made-up passport scan", name="passport.jpg"),
        original_name="passport.jpg",
        title="Passport",
    )
    with schema_context("practice_b"):
        b_owner = owner()
        http = Client(HTTP_HOST=B_HOST)
        sign_in(http, b_owner)
        for view in ("clients:document_download", "clients:document_preview"):
            url = reverse(view, kwargs={"public_id": document.public_id})
            assert http.get(url).status_code == 404, view
        assert not Document.objects.filter(public_id=document.public_id).exists()
        from django.core.files.storage import default_storage

        assert not default_storage.exists(document.file.name)
