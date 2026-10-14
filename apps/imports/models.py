"""Import runs, saved column matchings, and the tag on every record a run created."""

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel


class Kind(models.TextChoices):
    CLIENTS = "clients", "Clients"
    CONTACTS = "contacts", "Contacts"
    SERVICES = "services", "Services and fees"


class SavedMatching(TimeStampedModel):
    """A named column matching, offered again when a file with the same headings arrives."""

    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=80)
    # Headings as found in the file, and the key used to recognise them again.
    headers = models.JSONField(default=list)
    header_key = models.CharField(max_length=500, db_index=True)
    # {heading: field name or ""}
    mapping = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "name"], name="one_matching_name_per_kind")
        ]

    def __str__(self) -> str:
        return self.name


class ImportRun(TimeStampedModel):
    class State(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        DONE = "done", "Imported"
        UNDONE = "undone", "Undone"

    class FetchState(models.TextChoices):
        NONE = "", "Not asked for"
        WAITING = "waiting", "Waiting for the worker"
        RUNNING = "running", "Fetching"
        DONE = "done", "Finished"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    file_name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    state = models.CharField(max_length=10, choices=State.choices, default=State.UPLOADED)
    encoding = models.CharField(max_length=20, blank=True)
    delimiter = models.CharField(max_length=2, blank=True)
    headers = models.JSONField(default=list)
    # The file's rows. Encrypted, because a file can carry tax references; cleared
    # once the import has run, so only the failures are kept.
    data = EncryptedTextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    mapping = models.JSONField(default=dict, blank=True)
    matching = models.ForeignKey(
        SavedMatching, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    overwrite = models.BooleanField(
        "overwrite fields that already have a value",
        default=False,
    )
    counts = models.JSONField(default=dict, blank=True)
    # Rows that failed, with the reason: a JSON list, encrypted for the same reason as data.
    failures = EncryptedTextField(blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    undone_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    undo_report = models.JSONField(default=list, blank=True)

    # "Fetch from Companies House", done by the worker with progress on the page.
    fetch_state = models.CharField(
        max_length=10, choices=FetchState.choices, default=FetchState.NONE, blank=True
    )
    fetch_total = models.PositiveIntegerField(default=0)
    fetch_done = models.PositiveIntegerField(default=0)
    fetch_failed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} import of {self.file_name}"

    @property
    def state_tone(self) -> str:
        return {"done": "green", "undone": "neutral", "uploaded": "accent"}.get(self.state, "")

    @property
    def fetch_active(self) -> bool:
        return self.fetch_state in (self.FetchState.WAITING, self.FetchState.RUNNING)


class ImportedRecord(TimeStampedModel):
    """One record an import created. `stamp` is its updated_at just after the import,
    so undo can tell whether anybody has changed it since."""

    class Model(models.TextChoices):
        CLIENT = "client", "Client"
        CONTACT = "contact", "Contact"
        LINK = "link", "Link between a contact and a client"
        SERVICE = "service", "Client service"

    run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="records")
    model = models.CharField(max_length=10, choices=Model.choices)
    object_id = models.PositiveBigIntegerField()
    label = models.CharField(max_length=250)
    stamp = models.DateTimeField()

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["model", "object_id"])]

    def __str__(self) -> str:
        return f"{self.get_model_display()}: {self.label}"
