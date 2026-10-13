from django.db import models

from apps.core.models import TimeStampedModel


class CompanySnapshot(TimeStampedModel):
    """What Companies House last said about one client's company, as it said it.

    The sync compares a fresh answer with this to find what changed.
    """

    client = models.OneToOneField(
        "clients.Client", on_delete=models.CASCADE, related_name="ch_snapshot"
    )
    company_number = models.CharField(max_length=8)
    etag = models.CharField(max_length=100, blank=True)
    profile = models.JSONField(default=dict, blank=True)
    officers = models.JSONField(default=list, blank=True)
    owners = models.JSONField(default=list, blank=True)
    filings = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField()
    # When officers, owners and filings were last fetched (they are not fetched every night).
    people_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    def __str__(self) -> str:
        return f"Companies House snapshot for {self.company_number}"
