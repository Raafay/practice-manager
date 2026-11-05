"""Creating a practice, and moving the original single-practice tables into one.

Both run from the command line only (create_practice, move_into_schema).
"""

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context, schema_exists

from .models import Domain, Practice

SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
DOMAIN_NAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9-]{1,63})*$")
BACKUP_MAX_AGE_SECONDS = 60 * 60


def check_new_practice(schema_name: str, domain: str) -> None:
    """Refuse a schema name or address that is malformed or already taken."""
    if not SCHEMA_NAME.match(schema_name) or schema_name.startswith("pg_"):
        raise ValidationError(
            "The schema name must be 2 to 41 lower-case letters, digits or underscores, "
            "starting with a letter."
        )
    if schema_name == get_public_schema_name():
        raise ValidationError("The public schema holds the list of practices, not a practice.")
    if not DOMAIN_NAME.match(domain):
        raise ValidationError(f"{domain!r} is not a web address such as fpas.example.com.")
    with schema_context(get_public_schema_name()):
        if Practice.objects.filter(schema_name=schema_name).exists() or schema_exists(schema_name):
            raise ValidationError(f"There is already a practice or schema called {schema_name}.")
        if Domain.objects.filter(domain=domain).exists():
            raise ValidationError(f"The address {domain} already belongs to a practice.")


def create_practice(*, name: str, schema_name: str, domain: str, verbosity: int = 0) -> Practice:
    """A new, empty practice: its schema with every table, and its address."""
    check_new_practice(schema_name, domain)
    with schema_context(get_public_schema_name()):
        practice = Practice(schema_name=schema_name, name=name)
        practice.save(verbosity=verbosity)  # creates the schema and runs the migrations
        Domain.objects.create(domain=domain, tenant=practice, is_primary=True)
    with schema_context(schema_name):
        from apps.core.models import PracticeSettings

        PracticeSettings.objects.update_or_create(pk=1, defaults={"practice_name": name})
    return practice


# ---------------------------------------------------------------------------
# Moving the original tables (from before there were several practices).


def backup_is_recent(path: Path, now: float | None = None) -> str:
    """Return "" if path is a database dump made in the last hour, else the reason not."""
    now = now or time.time()
    if not path.is_file():
        return f"No backup file at {path}."
    if path.stat().st_size == 0:
        return f"The backup {path} is empty."
    if now - path.stat().st_mtime > BACKUP_MAX_AGE_SECONDS:
        return f"The newest backup ({path.name}) is more than an hour old."
    with path.open("rb") as handle:
        start = handle.read(4096)
    if not (start.startswith(b"PGDMP") or b"PostgreSQL database dump" in start):
        return f"{path.name} does not look like a pg_dump backup."
    return ""


def newest_backup(directory: Path) -> Path | None:
    dumps = sorted(directory.glob("db_*.dump"), key=lambda p: p.stat().st_mtime)
    return dumps[-1] if dumps else None


def _shared_tables() -> set[str]:
    """Tables that stay in the public schema: the practice list and the cache table."""
    from django.apps import apps

    tables = {
        model._meta.db_table
        for model in apps.get_app_config("tenancy").get_models(include_auto_created=True)
    }
    for cache in settings.CACHES.values():
        if cache.get("BACKEND", "").endswith("DatabaseCache"):
            tables.add(cache["LOCATION"])
    return tables


def _app_labels(app_names) -> set[str]:
    from django.apps import apps

    labels = set()
    for config in apps.get_app_configs():
        full = f"{config.__module__}.{config.__class__.__name__}"
        if config.name in app_names or full in app_names:
            labels.add(config.label)
    return labels


def _relations(cursor, schema: str) -> list[tuple[str, str]]:
    """(name, kind) of every table, view and stand-alone sequence in the schema.

    Sequences that belong to a column move with their table, so they are left out.
    """
    cursor.execute(
        """
        SELECT c.relname, c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
          AND NOT (c.relkind = 'S' AND EXISTS (
              SELECT 1 FROM pg_depend d
              WHERE d.objid = c.oid AND d.classid = 'pg_class'::regclass
                AND d.deptype IN ('a', 'i')))
          AND NOT c.relispartition
        ORDER BY c.relname
        """,
        [schema],
    )
    return list(cursor.fetchall())


def _q(*parts: str) -> str:
    return ".".join(connection.ops.quote_name(part) for part in parts)


def _count(cursor, schema: str, table: str) -> int:
    cursor.execute(f"SELECT count(*) FROM {_q(schema, table)}")  # noqa: S608 - quoted names
    return cursor.fetchone()[0]


def _copy_table_back(cursor, table: str, source: str, target: str, apps=None) -> None:
    """Give the source schema its own copy of a table that both schemas need
    (only the rows of the given apps, if named)."""
    cursor.execute(f"CREATE TABLE {_q(source, table)} (LIKE {_q(target, table)} INCLUDING ALL)")
    where, params = ("WHERE app = ANY(%s)", [sorted(apps)]) if apps is not None else ("", [])
    cursor.execute(
        f"INSERT INTO {_q(source, table)} SELECT * FROM {_q(target, table)} {where}",  # noqa: S608
        params,
    )
    highest = f"SELECT COALESCE(max(id), 0) + 1 FROM {_q(source, table)}"  # noqa: S608
    cursor.execute(
        f"SELECT setval(pg_get_serial_sequence(%s, 'id'), ({highest}), false)",
        [_q(source, table)],
    )


@dataclass
class MoveResult:
    practice: Practice
    counts: dict[str, int] = field(default_factory=dict)
    files_moved: int = 0
    files_note: str = ""


def move_into_schema(
    *, schema_name: str, domain: str, name: str = "", source: str = "public"
) -> MoveResult:
    """Move the single practice's tables from `source` into a new schema, as one practice.

    Every table, view and sequence except the practice list and the cache table is
    moved with ALTER ... SET SCHEMA inside one transaction, the row counts are
    compared, and the practice and its address are created. The migration history
    and content types are copied back, so the source schema stays consistent. If
    anything fails, nothing has changed. Uploaded files are moved afterwards.
    """
    check_new_practice(schema_name, domain)
    shared = _shared_tables()
    shared_labels = _app_labels(settings.SHARED_APPS)
    connection.set_schema_to_public()
    with transaction.atomic(), connection.cursor() as cursor:
        relations = [(n, k) for n, k in _relations(cursor, source) if n not in shared]
        names = {n for n, _ in relations}
        if "accounts_user" not in names:
            raise ValidationError(f"The {source} schema has no practice tables to move.")
        if not name:
            cursor.execute(
                f"SELECT practice_name FROM {_q(source, 'core_practicesettings')} "  # noqa: S608
                "ORDER BY id LIMIT 1"
            )
            row = cursor.fetchone()
            name = row[0] if row else schema_name
        tables = [n for n, k in relations if k in ("r", "p")]
        before = {table: _count(cursor, source, table) for table in tables}

        cursor.execute(f"CREATE SCHEMA {_q(schema_name)}")
        statement = {"v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE", "f": "FOREIGN TABLE"}
        for relation, kind in relations:
            cursor.execute(
                f"ALTER {statement.get(kind, 'TABLE')} {_q(source, relation)} "
                f"SET SCHEMA {_q(schema_name)}"
            )
        after = {table: _count(cursor, schema_name, table) for table in tables}
        if after != before:
            changed = sorted(t for t in tables if before[t] != after[t])
            raise RuntimeError(f"Row counts changed during the move: {changed}")

        # Both schemas keep a migration history and content types: the practice keeps
        # the full ones, the source keeps the shared apps' history and a copy of the types.
        # (Like every practice schema, the practice's history also lists the shared apps.)
        _copy_table_back(cursor, "django_migrations", source, schema_name, shared_labels)
        if "django_content_type" in names:
            _copy_table_back(cursor, "django_content_type", source, schema_name)

        practice = Practice(schema_name=schema_name, name=name)
        practice.auto_create_schema = False  # the schema was made above, with the data in it
        practice.save()
        Domain.objects.create(domain=domain, tenant=practice, is_primary=True)

    # Nothing should be left to run; this also checks the moved history is complete.
    call_command(
        "migrate_schemas", schema_name=schema_name, tenant=True, interactive=False, verbosity=0
    )
    connection.set_schema_to_public()
    result = MoveResult(practice=practice, counts=after)
    result.files_moved, result.files_note = move_files(source, schema_name)
    return result


def move_files(source: str, schema_name: str) -> tuple[int, str]:
    """Move uploaded files into the practice's folder (MEDIA_ROOT/<schema>/).

    Before there were practices, files sat at the top of MEDIA_ROOT. Folders that
    already belong to a practice are left alone. Only files on disk can be moved
    here; for a bucket the command prints what to run instead.
    """
    from apps.core.storage import EncryptedFileSystemStorage

    backend = settings.STORAGES["default"]["BACKEND"]
    if not backend.endswith("EncryptedFileSystemStorage"):
        return 0, (
            f"Files are in a bucket. Move them into the folder {schema_name}/ with your "
            f"provider's tools, for example: aws s3 mv s3://BUCKET/ s3://BUCKET/{schema_name}/ "
            f"--recursive --exclude '{schema_name}/*' (leave other practices' folders alone)."
        )
    root = Path(EncryptedFileSystemStorage().base_location)
    origin = root if source == get_public_schema_name() else root / source
    if not origin.is_dir():
        return 0, "There were no uploaded files to move."
    target = root / schema_name
    target.mkdir(parents=True, exist_ok=True)
    with schema_context(get_public_schema_name()):
        practice_folders = set(Practice.objects.values_list("schema_name", flat=True))
    moved = 0
    for entry in sorted(origin.iterdir()):
        if origin == root and entry.name in practice_folders:
            continue
        destination = target / entry.name
        if destination.exists():
            raise FileExistsError(f"{destination} is already there; nothing more was moved.")
        shutil.move(str(entry), str(destination))
        if destination.is_dir():
            moved += sum(len(files) for _, _, files in os.walk(destination))
        else:
            moved += 1
    return moved, ""
