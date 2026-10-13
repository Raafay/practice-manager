import pytest

from apps.companieshouse import fake


@pytest.fixture(autouse=True)
def _fresh_fake():
    fake.reset()
    yield
    fake.reset()


@pytest.fixture
def ch():
    """The fake Companies House. Use `ch.set(path, data)` to change an answer."""
    return fake.fake_transport()
