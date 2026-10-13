"""A fixed-window rate limiter on the Django cache.

The database cache is used in production, so limits hold across processes.
Keys are hashed, so a token never sits in the cache in readable form.
"""

import hashlib

from django.core.cache import cache


def _cache_key(key: str) -> str:
    return "rl:" + hashlib.sha256(key.encode()).hexdigest()


def hit(key: str, limit: int, period_seconds: int) -> bool:
    """Count one attempt. Return True if it is within the limit, False if over it."""
    cache_key = _cache_key(key)
    if cache.add(cache_key, 1, timeout=period_seconds):
        return True
    try:
        count = cache.incr(cache_key)
    except ValueError:  # expired between add and incr
        cache.set(cache_key, 1, timeout=period_seconds)
        count = 1
    return count <= limit


def is_limited(key: str, limit: int) -> bool:
    """True if the key has already used up its limit. Does not count an attempt."""
    return (cache.get(_cache_key(key)) or 0) >= limit


def reset(key: str) -> None:
    cache.delete(_cache_key(key))


def client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR", "")
