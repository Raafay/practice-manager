"""Seed the three roles with the rights in docs/specs/01-security-and-users.md section 2.

The lists are copied here on purpose, so that later changes to the defaults in
rights.py never change what this migration did.
"""

from django.db import migrations

MANAGER = [
    "fees.view",
    "documents.sensitive",
    "comms.approve",
    "comms.approve_fees",
    "comms.pause",
    "settings.manage",
    "data.export",
    "clients.status",
    "clients.archive",
    "time.edit_all",
]
STAFF = ["fees.view", "documents.sensitive", "comms.approve"]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.update_or_create(slug="owner", defaults={"name": "Owner", "order": 1, "rights": []})
    Role.objects.update_or_create(slug="manager", defaults={"name": "Manager", "order": 2, "rights": MANAGER})
    Role.objects.update_or_create(slug="staff", defaults={"name": "Staff", "order": 3, "rights": STAFF})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(seed_roles, migrations.RunPython.noop)]
