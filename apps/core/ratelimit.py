"""A fixed-window rate limiter on the Django cache.

The database cache is used in production, so limits hold across processes.
Keys are hashed, so a token never sits in the cache in readable form.
"""

import hashlib
import ipaddress

from django.conf import settings
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


def _valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


def client_ip(request) -> str:
    """The visitor's address, for rate limits, lockout and the activity log.

    Behind the host's proxy REMOTE_ADDR is the proxy itself. With
    TRUSTED_CLIENT_IP_HEADER set (a header the host's proxy always overwrites), that
    header is used. With TRUSTED_PROXY_COUNT = N, the Nth address from the right of
    X-Forwarded-For is used: the entries to its left were written by the visitor and
    can be made up. With neither set, REMOTE_ADDR is used.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    header = getattr(settings, "TRUSTED_CLIENT_IP_HEADER", "")
    if header:
        key = "HTTP_" + header.upper().replace("-", "_")
        return _valid_ip(request.META.get(key, "")) or remote
    count = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if count > 0:
        forwarded = [
            part.strip()
            for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= count:
            return _valid_ip(forwarded[-count]) or remote
    return remote
