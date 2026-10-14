from django.db import migrations

from apps.pipeline import seed


def run(apps, schema_editor):
    Stage = apps.get_model("pipeline", "PipelineStage")
    Settings = apps.get_model("pipeline", "PipelineSettings")
    Template = apps.get_model("comms", "MessageTemplate")
    for position, (key, name, chance, is_open, won, lost, hold, colour) in enumerate(seed.STAGES):
        Stage.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "position": position,
                "chance": chance,
                "is_open": is_open,
                "is_won": won,
                "is_lost": lost,
                "is_on_hold": hold,
                "colour": colour,
            },
        )
    Settings.objects.get_or_create(
        pk=1,
        defaults={"opening_text": seed.OPENING_TEXT, "what_next_html": seed.WHAT_NEXT_HTML},
    )
    item = seed.TEMPLATE
    Template.objects.get_or_create(
        key=item["key"],
        defaults={
            "name": item["name"],
            "group": item["group"],
            "channel": "email",
            "subject": item["subject"],
            "body": item["body"],
            "send_mode": item["send_mode"],
            "active": True,
            "system": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pipeline", "0001_initial"),
        ("comms", "0002_seed_templates_and_schedules"),
    ]
    operations = [migrations.RunPython(run, migrations.RunPython.noop)]
