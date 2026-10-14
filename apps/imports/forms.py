from django import forms

from .fields import FIELDS
from .models import ImportRun, Kind
from .reading import MAX_BYTES


class UploadForm(forms.Form):
    kind = forms.ChoiceField(
        label="What the file holds",
        choices=Kind.choices,
        widget=forms.RadioSelect,
        initial=Kind.CLIENTS,
        help_text="Import clients first, then contacts, then services and fees.",
    )
    file = forms.FileField(
        label="CSV file",
        help_text="Saved from a spreadsheet or exported from the old system. Up to 5 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.txt,text/csv"}),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".csv", ".txt")):
            raise forms.ValidationError("Choose a .csv file. Save the spreadsheet as CSV first.")
        if upload.size > MAX_BYTES:
            raise forms.ValidationError("The file is larger than 5 MB. Split it into parts.")
        return upload


class MappingForm(forms.Form):
    """One drop-down per column of the file."""

    overwrite = forms.BooleanField(
        label="Overwrite details that already have a value",
        required=False,
        help_text="Without this, a row that matches a record only fills its empty fields.",
    )
    save_as = forms.CharField(
        label="Save this matching as",
        required=False,
        max_length=80,
        help_text="For example “Old system clients”. Offered again when a file with the same "
        "headings is uploaded.",
    )

    def __init__(self, *args, run: ImportRun, **kwargs):
        super().__init__(*args, **kwargs)
        self.run = run
        choices = [("", "Ignore this column")] + [(f.key, f.label) for f in FIELDS[run.kind]]
        self.columns = []
        for i, heading in enumerate(run.headers):
            name = f"col_{i}"
            self.fields[name] = forms.ChoiceField(
                label=heading,
                choices=choices,
                required=False,
                initial=run.mapping.get(heading, ""),
            )
            self.columns.append(name)
        self.fields["overwrite"].initial = run.overwrite
        if run.matching:
            self.fields["save_as"].initial = ""

    def mapping(self) -> dict:
        return {h: self.cleaned_data.get(f"col_{i}", "") for i, h in enumerate(self.run.headers)}

    def column_fields(self):
        return [self[name] for name in self.columns]
