"""Practices served by this installation, each in its own PostgreSQL schema.

These two tables live in the public schema. Everything about a practice's
clients lives in the practice's own schema (docs/MULTITENANT.md).
"""

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Practice(TenantMixin):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        READ_ONLY = "read_only", "Read-only"
        CLOSING = "closing", "Closing"

    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Saving a new practice creates its schema and runs every migration in it.
    # Deleting the row never drops the schema; that is a separate, deliberate step.
    auto_create_schema = True
    auto_drop_schema = False

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def primary_domain(self) -> str:
        domain = self.domains.filter(is_primary=True).first() or self.domains.first()
        return domain.domain if domain else ""


class Domain(DomainMixin):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain"]

    def __str__(self) -> str:
        return self.domain
