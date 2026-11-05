"""Encrypt uploaded files that were stored before encryption was switched on. Safe to run twice."""

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models

from apps.tenancy.commands import PracticeCommand


class Command(PracticeCommand):
    help = (
        "Encrypt any uploaded file that is still stored in plain form, in every practice "
        "(or one, with --practice)."
    )
    every_practice_by_default = True

    def handle(self, *args, **options):
        storage = default_storage
        if not hasattr(storage, "is_encrypted"):
            self.stdout.write("The file storage does not encrypt; nothing done.")
            return
        done = 0
        for model in apps.get_models():
            fields = [f.name for f in model._meta.fields if isinstance(f, models.FileField)]
            for name in fields:
                for value in model._default_manager.exclude(**{name: ""}).values_list(
                    name, flat=True
                ):
                    if not value or not storage.exists(value) or storage.is_encrypted(value):
                        continue
                    with storage.open(value) as handle:
                        data = handle.read()
                    storage.delete(value)
                    storage.save(value, ContentFile(data))
                    done += 1
        self.stdout.write(f"Encrypted {done} file(s).")
