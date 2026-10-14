from django.db import migrations

# Stage 10 builds the upload and confirmation pages, so the starter wording points to them
# (docs/STATUS.md, Stage 6 assumption 6). A template the practice has already rewritten no
# longer contains these exact sentences and is left alone.
REPLACEMENTS = {
    "accounts_records": [
        (
            "Please reply to this email with everything attached.</p>",
            "Please upload everything with the button below, or reply to this email with it "
            "attached.</p><p>{{ upload_link }}</p>",
        )
    ],
    "vat_records": [
        (
            "Reply to this email with them attached.</p>",
            "Use the button below to upload them, or reply to this email with them "
            "attached.</p><p>{{ upload_link }}</p>",
        )
    ],
    "sa_records": [
        (
            "Reply to this email with them attached.</p>",
            "Use the button below to upload them, or reply to this email with them "
            "attached.</p><p>{{ upload_link }}</p>",
        )
    ],
    "confirmation_statement": [
        (
            "<p>If it is all correct, just reply to say so.</p>",
            "<p>Please use the button below to tell us if anything has changed. If nothing has, "
            "it takes a few seconds.</p><p>{{ confirm_link }}</p>",
        )
    ],
}

ACK_BODY = (
    "<p>Dear {{ contact.first_name }},</p><p>Thank you. We have your request and will get back "
    "to you. Your reference is {reference}.</p><p>Kind regards,<br>{{ practice.name }}</p>"
)


def update(apps, schema_editor):
    Template = apps.get_model("comms", "MessageTemplate")
    for key, pairs in REPLACEMENTS.items():
        template = Template.objects.filter(key=key).first()
        if template is None:
            continue
        body = template.body
        for old, new in pairs:
            body = body.replace(old, new)
        if body != template.body:
            template.body = body
            template.save(update_fields=["body", "updated_at"])
    Template.objects.get_or_create(
        key="request_acknowledgement",
        defaults={
            "name": "Request received: acknowledgement",
            "group": "general",
            "subject": "We have your request ({reference})",
            "body": ACK_BODY,
            "channel": "email",
            "send_mode": "hold",
            "active": False,
            "system": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0001_initial"),
        ("comms", "0002_seed_templates_and_schedules"),
    ]
    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
