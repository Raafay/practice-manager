"""Cached values and rate limits stay inside their practice."""

from django.core.cache import cache
from django_tenants.utils import schema_context

from apps.core import ratelimit


def test_a_cache_key_names_the_practice():
    assert cache.make_key("x").startswith("practice_a:")
    with schema_context("practice_b"):
        assert cache.make_key("x").startswith("practice_b:")


def test_a_value_cached_in_one_practice_is_not_seen_in_the_other():
    cache.set("practice-name", "A's name")
    with schema_context("practice_b"):
        assert cache.get("practice-name") is None
        cache.set("practice-name", "B's name")
    assert cache.get("practice-name") == "A's name"


def test_a_rate_limit_hit_in_one_practice_does_not_count_in_the_other():
    assert ratelimit.hit("login:203.0.113.9", limit=2, period_seconds=60)
    assert ratelimit.hit("login:203.0.113.9", limit=2, period_seconds=60)
    assert not ratelimit.hit("login:203.0.113.9", limit=2, period_seconds=60)
    assert ratelimit.is_limited("login:203.0.113.9", limit=2)
    with schema_context("practice_b"):
        assert not ratelimit.is_limited("login:203.0.113.9", limit=2)
        assert ratelimit.hit("login:203.0.113.9", limit=2, period_seconds=60)
