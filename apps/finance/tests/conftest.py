from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance import xero, xero_fake
from apps.finance.models import XeroConnection


@pytest.fixture(autouse=True)
def _fresh_fake():
    xero_fake.reset()
    yield
    xero_fake.reset()


@pytest.fixture
def fake():
    return xero_fake.fake_transport()


@pytest.fixture
def connection(db):
    """A connected organisation with a token that is still good."""
    return XeroConnection.objects.create(
        tenant_id="00000000-0000-4000-8000-0000000000a1",
        tenant_name="Demo Practice Ltd",
        access_token="access-start",
        refresh_token="refresh-start",
        expires_at=timezone.now() + timedelta(minutes=20),
    )


@pytest.fixture
def expired(connection):
    connection.expires_at = timezone.now() - timedelta(minutes=5)
    connection.save()
    return connection


__all__ = ["xero"]
