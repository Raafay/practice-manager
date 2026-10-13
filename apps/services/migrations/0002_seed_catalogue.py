from django.db import migrations

from apps.services.catalogue import SEED


def seed(apps, schema_editor):
    Service = apps.get_model("services", "Service")
    for position, (code, name, kind, applies_to, rules, renewal) in enumerate(SEED, start=1):
        Service.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "kind": kind,
                "applies_to": applies_to,
                "rules": rules,
                "renewal": renewal,
                "position": position * 10,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("services", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
