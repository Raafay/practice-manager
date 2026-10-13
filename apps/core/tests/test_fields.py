import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.core.management import call_command
from django.db import connection

from apps.core.fields import _fernet, mask
from apps.core.tests.encrypted_app.models import Secret

pytestmark = pytest.mark.django_db

SAMPLE = "QQ000000A"  # not a real NI number format in use


def raw_value(pk: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT value FROM {Secret._meta.db_table} WHERE id = %s", [pk])  # noqa: S608
        return cursor.fetchone()[0]


def test_stores_ciphertext_not_the_value():
    secret = Secret.objects.create(label="a", value=SAMPLE)
    stored = raw_value(secret.pk)
    assert SAMPLE not in stored
    assert stored.startswith("gAAAA")  # a Fernet token
    assert Secret.objects.get(pk=secret.pk).value == SAMPLE


def test_same_value_encrypts_differently_each_time():
    first = Secret.objects.create(label="a", value=SAMPLE)
    second = Secret.objects.create(label="b", value=SAMPLE)
    assert raw_value(first.pk) != raw_value(second.pk)


def test_empty_and_null_are_kept_as_they_are():
    blank = Secret.objects.create(label="blank", value="")
    null = Secret.objects.create(label="null", value=None)
    assert raw_value(blank.pk) == ""
    assert raw_value(null.pk) is None
    assert Secret.objects.filter(value__isnull=True).count() == 1


def test_cannot_be_searched():
    with pytest.raises(FieldError):
        list(Secret.objects.filter(value=SAMPLE))


def test_survives_key_rotation(settings):
    old_key = settings.FIELD_ENCRYPTION_KEYS[0]
    secret = Secret.objects.create(label="a", value=SAMPLE)
    old_token = raw_value(secret.pk)

    # A new key goes in front. Old values still read.
    new_key = Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [new_key, old_key]
    _fernet.cache_clear()
    assert Secret.objects.get(pk=secret.pk).value == SAMPLE

    # Re-encrypt everything with the new key, then drop the old key.
    call_command("rotate_encryption_keys", stdout=open("/dev/null", "w"))  # noqa: SIM115
    assert raw_value(secret.pk) != old_token
    settings.FIELD_ENCRYPTION_KEYS = [new_key]
    _fernet.cache_clear()
    assert Secret.objects.get(pk=secret.pk).value == SAMPLE


def test_unreadable_without_the_key(settings):
    secret = Secret.objects.create(label="a", value=SAMPLE)
    settings.FIELD_ENCRYPTION_KEYS = [Fernet.generate_key().decode()]
    _fernet.cache_clear()
    with pytest.raises(ImproperlyConfigured):
        Secret.objects.get(pk=secret.pk)


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("QQ123456A", "••••••56A"),
        ("1234567890", "••••••890"),
        ("AB", "••••••"),
        ("", ""),
        (None, ""),
    ],
)
def test_mask(value, shown):
    assert mask(value) == shown
