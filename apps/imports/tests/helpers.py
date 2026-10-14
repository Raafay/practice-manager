"""Helpers for import tests. Every file and person here is made up."""

from pathlib import Path

from apps.accounts.tests.factories import owner, staff
from apps.imports import services

SAMPLES = Path(__file__).parent / "samples"


def boss():
    """The owner. The same person each time it is called in a test."""
    from apps.accounts.models import User

    found = User.objects.filter(email="morgan.sample@example.com").first()
    return found or owner(name="Morgan Sample", email="morgan.sample@example.com")


def sam():
    """The manager named in the sample files."""
    from apps.accounts.models import User

    found = User.objects.filter(email="sam.example@example.com").first()
    return found or staff(name="Sam Example", email="sam.example@example.com")


def upload(actor, kind: str, name: str, raw: bytes | None = None):
    data = raw if raw is not None else (SAMPLES / name).read_bytes()
    return services.start_run(actor, kind, name, data)


def ready(actor, kind: str, name: str, raw: bytes | None = None, **options):
    """Uploaded with the suggested matching accepted."""
    run = upload(actor, kind, name, raw)
    return services.set_mapping(actor, run, run.mapping, overwrite=options.get("overwrite", False))


def imported(actor, kind: str, name: str, raw: bytes | None = None, **options):
    return services.run_import(actor, ready(actor, kind, name, raw, **options))


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()
