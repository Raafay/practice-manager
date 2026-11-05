"""Cache keys carry the practice's schema, so cached values and rate limits
never cross from one practice to another."""

from django.db import connection


def make_key(key: str, key_prefix: str, version: int) -> str:
    schema = getattr(connection, "schema_name", "") or "public"
    return f"{schema}:{key_prefix}:{version}:{key}"
