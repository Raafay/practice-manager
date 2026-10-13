from django.db import migrations

from apps.comms.seed import SCHEDULES, TEMPLATES


def seed(apps, schema_editor):
    Template = apps.get_model("comms", "MessageTemplate")
    Schedule = apps.get_model("comms", "ReminderSchedule")
    made = {}
    for item in TEMPLATES:
        made[item["key"]], _ = Template.objects.get_or_create(
            key=item["key"],
            defaults={
                "name": item["name"],
                "group": item["group"],
                "subject": item["subject"],
                "body": item["body"],
                "channel": "email",
                "send_mode": "hold",
                "active": True,
                "system": True,
            },
        )
    for item in SCHEDULES:
        Schedule.objects.get_or_create(
            key=item["key"],
            defaults={
                "name": item["name"],
                "template": made[item["key"]],
                "rule": item["rule"],
                "trigger": item["trigger"],
                "offsets": item["offsets"],
                "working_days": item.get("working_days", False),
                "repeat_every_days": item.get("repeat_every_days"),
                "max_repeats": item.get("max_repeats", 0),
                "description": item["description"],
                "active": False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("comms", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
