from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.fields import encrypted_fields


class Command(BaseCommand):
    help = (
        "Re-encrypt every encrypted field with the first key in FIELD_ENCRYPTION_KEYS. "
        "Run after putting a new key at the front; the old key can then be removed."
    )

    def handle(self, *args, **options):
        total = 0
        for model, names in encrypted_fields():
            with transaction.atomic():
                for obj in model._default_manager.select_for_update().only("pk", *names):
                    values = {name: getattr(obj, name) for name in names}
                    # Saving re-encrypts with the active key. update() skips signals and timestamps.
                    model._default_manager.filter(pk=obj.pk).update(**values)
                    total += 1
            self.stdout.write(f"{model._meta.label}: {', '.join(names)}")
        self.stdout.write(self.style.SUCCESS(f"Re-encrypted {total} rows."))
