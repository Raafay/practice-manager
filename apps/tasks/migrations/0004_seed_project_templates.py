from django.db import migrations

from apps.tasks import catalogue


def seed(apps, schema_editor):
    Template = apps.get_model("tasks", "ProjectTemplate")
    Section = apps.get_model("tasks", "ProjectTemplateSection")
    Item = apps.get_model("tasks", "ProjectTemplateTask")
    Category = apps.get_model("tasks", "TaskCategory")
    for position, (name, description, sections) in enumerate(catalogue.PROJECT_TEMPLATES, 1):
        template, created = Template.objects.get_or_create(
            name=name, defaults={"description": description, "position": position * 10}
        )
        if not created:
            continue
        order = 0
        for s_position, (section_name, items) in enumerate(sections, 1):
            section = Section.objects.create(
                template=template, name=section_name, position=s_position * 10
            )
            for title, category, minutes, offset in items:
                order += 10
                Item.objects.create(
                    template=template,
                    section=section,
                    title=title,
                    category=Category.objects.filter(name=category).first(),
                    estimate_minutes=minutes,
                    day_offset=offset,
                    position=order,
                )


class Migration(migrations.Migration):
    dependencies = [("tasks", "0003_projects_repeating_tasks")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
