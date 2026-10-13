import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """The cache outlives each test's database rollback, so clear it both sides."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
