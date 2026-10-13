from django.db import migrations

from apps.tasks import catalogue


def seed(apps, schema_editor):
    Status = apps.get_model("tasks", "TaskStatus")
    Category = apps.get_model("tasks", "TaskCategory")
    Template = apps.get_model("tasks", "TaskTemplate")
    Step = apps.get_model("tasks", "TaskTemplateStep")
    Service = apps.get_model("services", "Service")

    for position, (name, colour, done, waiting, default) in enumerate(catalogue.STATUSES, 1):
        Status.objects.get_or_create(
            name=name,
            defaults={
                "colour": colour,
                "is_done": done,
                "is_waiting": waiting,
                "is_default": default,
                "position": position * 10,
            },
        )
    for position, (name, kind, colour) in enumerate(catalogue.CATEGORIES, 1):
        Category.objects.get_or_create(
            name=name, defaults={"kind": kind, "colour": colour, "position": position * 10}
        )
    if Template.objects.exists():
        return
    for position, (code, rule, pattern, category, target, steps) in enumerate(
        catalogue.TEMPLATES, 1
    ):
        service = Service.objects.filter(code=code).first()
        if service is None:
            continue
        kind, value = target
        template = Template.objects.create(
            service=service,
            rule=rule,
            name_pattern=pattern,
            category=Category.objects.get(name=category),
            default_owner="manager",
            target_kind=kind,
            target_days=value if isinstance(value, int) else 0,
            target_month=value[0] if isinstance(value, tuple) else None,
            target_day=value[1] if isinstance(value, tuple) else None,
            position=position * 10,
        )
        for order, (step_name, flags) in enumerate(steps, 1):
            Step.objects.create(
                template=template,
                name=step_name,
                position=order * 10,
                stops_reminders="S" in flags,
                is_filing="F" in flags,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
        ("services", "0002_seed_catalogue"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
