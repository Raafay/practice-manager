"""create_practice and move_into_schema (Stage 14, item 5)."""

import io
import os
import time

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import Client
from django_tenants.utils import schema_context

from apps.tenancy.models import Domain, Practice
from apps.tenancy.services import backup_is_recent


def _drop(*schemas):
    connection.set_schema_to_public()
    with connection.cursor() as cursor:
        for schema in schemas:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    Domain.objects.filter(tenant__schema_name__in=schemas).delete()
    Practice.objects.filter(schema_name__in=schemas).delete()


@pytest.fixture
def backup(tmp_path):
    path = tmp_path / "db_2026-11-05_0900.dump"
    path.write_bytes(b"PGDMP made-up dump for the test")
    return path


def test_a_backup_must_be_a_recent_dump(tmp_path, backup):
    assert backup_is_recent(backup) == ""
    assert "No backup" in backup_is_recent(tmp_path / "missing.dump")
    old = time.time() - 2 * 60 * 60
    os.utime(backup, (old, old))
    assert "more than an hour old" in backup_is_recent(backup)
    other = tmp_path / "db_other.dump"
    other.write_bytes(b"not a dump")
    assert "does not look like" in backup_is_recent(other)


@pytest.mark.django_db
def test_move_refuses_without_a_recent_backup(tmp_path):
    with pytest.raises(CommandError, match="Take a fresh backup"):
        call_command(
            "move_into_schema", "fpas", "--domain", "fpas.testserver", "--noinput",
            "--backup", str(tmp_path / "none.dump"),
        )  # fmt: skip
    with schema_context("public"):
        assert not Practice.objects.filter(schema_name="fpas").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "schema, domain, message",
    [
        ("public", "x.testserver", "public schema"),
        ("practice_b", "x.testserver", "already a practice"),
        ("new_one", "other.testserver", "already belongs"),
        ("Bad-Name", "x.testserver", "lower-case"),
        ("new_one", "not a domain", "not a web address"),
    ],
)
def test_create_practice_refuses_a_taken_or_bad_name(schema, domain, message):
    with pytest.raises(CommandError, match=message):
        call_command("create_practice", "New", schema, domain, "owner@example.com")


@pytest.mark.django_db(transaction=True)
def test_create_practice_makes_an_empty_practice_and_invites_its_owner():
    out = io.StringIO()
    try:
        call_command(
            "create_practice", "Example Accountants", "example", "example.testserver",
            "owner@example.com", stdout=out,
        )  # fmt: skip
        assert "http://example.testserver/" in out.getvalue()
        with schema_context("example"):
            from apps.accounts.models import Invitation, User
            from apps.clients.models import Client as ClientRecord
            from apps.core.models import PracticeSettings

            assert PracticeSettings.load().practice_name == "Example Accountants"
            assert ClientRecord.objects.count() == 0
            assert User.objects.count() == 0
            invitation = Invitation.objects.get()
            assert invitation.role.slug == "owner"
        assert mail.outbox[-1].to == ["owner@example.com"]
        assert "http://example.testserver/invite/" in mail.outbox[-1].body
        response = Client().get("/login/", HTTP_HOST="example.testserver")
        assert response.status_code == 200
    finally:
        _drop("example")


def _counts(schema):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            [schema],
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        counts = {}
        for table in tables:
            cursor.execute(f'SELECT count(*) FROM "{schema}"."{table}"')  # noqa: S608
            counts[table] = cursor.fetchone()[0]
    return counts


@pytest.mark.django_db(transaction=True)
def test_moving_a_copy_of_the_demo_data_keeps_every_count_and_every_page(
    backup, settings, tmp_path
):
    """The demo data stands in for the original tables: it is loaded into a schema of
    its own ("legacy", like the old public schema), with an uploaded file at the top of
    its folder, then moved into "moved" and visited on the new address."""
    from apps.core.tests import test_url_walk as walk

    try:
        with schema_context("public"):
            legacy = Practice(schema_name="legacy", name="Legacy")
            legacy.save(verbosity=0)
            Domain.objects.create(domain="legacy.testserver", tenant=legacy, is_primary=True)
        with schema_context("legacy"):
            call_command("seed_demo", verbosity=0, stdout=io.StringIO())
            from apps.clients.models import Document

            document = Document.objects.filter(deleted_at__isnull=True).first()
            stored_name = document.file.name
            with document.file.open() as handle:
                original_bytes = handle.read()
        with schema_context("public"):
            Domain.objects.filter(tenant__schema_name="legacy").delete()
            Practice.objects.filter(schema_name="legacy").delete()  # keeps the schema
        before = _counts("legacy")
        assert before["clients_client"] > 0

        out = io.StringIO()
        call_command(
            "move_into_schema", "moved", "--from", "legacy", "--domain", "moved.testserver",
            "--backup", str(backup), "--noinput", stdout=out,
        )  # fmt: skip
        assert "every count the same" in out.getvalue()

        after = _counts("moved")
        assert after == before
        # The old schema keeps only the shared migration history and content types.
        assert set(_counts("legacy")) == {"django_migrations", "django_content_type"}
        with schema_context("public"):
            moved = Practice.objects.get(schema_name="moved")
            assert moved.primary_domain == "moved.testserver"
            assert moved.name == "Hale & Castell Accountants (demo)"

        with schema_context("moved"):
            from apps.accounts.models import User

            # Files moved into the new practice's folder and still open there.
            assert (tmp_path / "media" / "moved" / stored_name).exists()
            document = Document.objects.get(pk=document.pk)
            with document.file.open() as handle:
                assert handle.read() == original_bytes

            # Every page: the owner visits every address with real records.
            world = walk.World()
            boss = User.objects.filter(role__slug="owner", is_active=True).first()
            http = Client(HTTP_HOST="moved.testserver", raise_request_exception=False)
            walk.sign_in(http, boss)
            failures = []
            for name, route in sorted(walk.all_patterns().items()):
                if walk.EXPECTED[name]["get"] in ("open", "refused"):
                    continue
                url = walk.reverse(name, kwargs=walk.fill_kwargs(world, name, route) or None)
                response = http.get(url)
                if response.status_code >= 500 or walk.is_sign_in_redirect(response):
                    failures.append(f"{name} {url}: {response.status_code}")
            assert not failures, "\n".join(failures)
    finally:
        _drop("legacy", "moved")
