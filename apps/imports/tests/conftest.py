import pytest

from apps.companieshouse import fake
from apps.imports.tests.helpers import sam


@pytest.fixture(autouse=True)
def _sample_manager(db):
    """The sample files name Sam Example as a manager."""
    return sam()


@pytest.fixture(autouse=True)
def _fresh_fake():
    fake.reset()
    yield
    fake.reset()
