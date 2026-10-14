from django.db import migrations

from apps.finance.chase import TEMPLATES


def seed(apps, schema_editor):
    Template = apps.get_model("comms", "MessageTemplate")
    for item in TEMPLATES:
        Template.objects.get_or_create(
            key=item["key"],
            defaults={
                "name": item["name"],
                "group": "fees",
                "subject": item["subject"],
                "body": item["body"],
                "channel": "email",
                "send_mode": "hold",
                "active": True,
                "system": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0001_initial"),
        ("comms", "0002_seed_templates_and_schedules"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
