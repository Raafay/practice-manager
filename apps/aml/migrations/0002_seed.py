from django.db import migrations

from apps.aml.seed import QUESTIONS, options_for


def seed(apps, schema_editor):
    Question = apps.get_model("aml", "RiskQuestion")
    if Question.objects.exists():
        return
    for position, (section, text, risky, score, enhanced, records, help_text) in enumerate(
        QUESTIONS, start=1
    ):
        Question.objects.create(
            section=section,
            text=text,
            help_text=help_text,
            answer_type="yes_no",
            options=options_for(risky, score, enhanced),
            records_check=records,
            position=position * 10,
        )
    apps.get_model("aml", "AmlSettings").objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("aml", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
