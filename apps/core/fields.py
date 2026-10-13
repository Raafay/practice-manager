"""An encrypted text field with key rotation, and a masked display helper.

Keys come from settings.FIELD_ENCRYPTION_KEYS, newest first. The first key
encrypts. Every key can decrypt, so a new key can be put in front of the list,
`manage.py rotate_encryption_keys` run, and the old key then removed.

Values are never searchable, and must never be written to events or logs.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import models

MASK = "••••••"


@lru_cache(maxsize=8)
def _fernet(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS is empty.")
    return MultiFernet([Fernet(key.encode() if isinstance(key, str) else key) for key in keys])


def get_fernet() -> MultiFernet:
    return _fernet(tuple(settings.FIELD_ENCRYPTION_KEYS))


def encrypt(value: str) -> str:
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "An encrypted value could not be read with any key in FIELD_ENCRYPTION_KEYS."
        ) from exc


def mask(value: str | None, visible: int = 3) -> str:
    """Show only the last few characters, for example ••••••12A."""
    if not value:
        return ""
    if len(value) <= visible:
        return MASK
    return MASK + value[-visible:]


class EncryptedTextField(models.TextField):
    description = "Text encrypted at rest"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return decrypt(value)

    def get_lookup(self, lookup_name):
        if lookup_name != "isnull":
            raise FieldError(f"Encrypted field '{self.name}' cannot be searched.")
        return super().get_lookup(lookup_name)


def encrypted_fields() -> list[tuple[type[models.Model], list[str]]]:
    """Every installed model with encrypted fields, with those field names."""
    from django.apps import apps

    found = []
    for model in apps.get_models():
        names = [f.name for f in model._meta.concrete_fields if isinstance(f, EncryptedTextField)]
        if names:
            found.append((model, names))
    return found
