import pytest
from django.core.cache import cache
from django.db import connection

# Two practices in the test database. Every test runs inside practice A, which
# answers on "testserver", the test client's default address. Practice B is there
# so tests can check that nothing crosses from one practice to the other.
PRACTICE_A = {"schema_name": "practice_a", "name": "Practice A", "domain": "testserver"}
PRACTICE_B = {"schema_name": "practice_b", "name": "Practice B", "domain": "other.testserver"}

_practices = {}


def ensure_practices():
    """Create both test practices (each with its own schema) if they are missing."""
    from apps.tenancy.models import Domain, Practice

    connection.set_schema_to_public()
    for spec in (PRACTICE_A, PRACTICE_B):
        practice = Practice.objects.filter(schema_name=spec["schema_name"]).first()
        if practice is None:
            practice = Practice(schema_name=spec["schema_name"], name=spec["name"])
            practice.save(verbosity=0)
        Domain.objects.get_or_create(
            domain=spec["domain"], defaults={"tenant": practice, "is_primary": True}
        )
        _practices[spec["schema_name"]] = practice
    connection.set_tenant(_practices["practice_a"])


def practice(schema_name="practice_a"):
    from apps.tenancy.models import Practice

    found = _practices.get(schema_name)
    if found is None:  # a test without the database: an unsaved stand-in is enough
        spec = PRACTICE_A if schema_name == "practice_a" else PRACTICE_B
        found = Practice(schema_name=spec["schema_name"], name=spec["name"])
    return found


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        ensure_practices()


@pytest.fixture(autouse=True)
def _inside_practice_a():
    connection.set_tenant(practice("practice_a"))
    yield
    # Leave the public schema out of the search path, so the database flush after a
    # transactional test empties practice A's tables but never the list of practices.
    connection.set_tenant(practice("practice_a"), include_public=False)


@pytest.fixture
def practice_a():
    return practice("practice_a")


@pytest.fixture
def practice_b():
    return practice("practice_b")


@pytest.fixture(autouse=True)
def _clear_cache():
    """The cache outlives each test's database rollback, so clear it both sides."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
