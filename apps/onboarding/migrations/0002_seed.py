from django.db import migrations

from apps.onboarding.seed import CHECKLIST, LETTER_PARTS, TEMPLATES


def seed(apps, schema_editor):
    Item = apps.get_model("onboarding", "ChecklistTemplateItem")
    Part = apps.get_model("onboarding", "LetterPart")
    Template = apps.get_model("comms", "MessageTemplate")
    for position, (key, name, needed, system) in enumerate(CHECKLIST):
        Item.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "needed_before_golive": needed,
                "system_ticked": system,
                "position": position,
            },
        )
    for key, (position, body) in LETTER_PARTS.items():
        Part.objects.get_or_create(key=key, defaults={"body": body, "position": position})
    for item in TEMPLATES:
        Template.objects.get_or_create(
            key=item["key"],
            defaults={
                "name": item["name"],
                "group": item["group"],
                "channel": item.get("channel", "email"),
                "subject": item["subject"],
                "body": item["body"],
                "send_mode": item["send_mode"],
                "active": True,
                "system": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0001_initial"),
        ("comms", "0002_seed_templates_and_schedules"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
