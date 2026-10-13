import re

from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.models import validate_hex_colour
from apps.services.models import Service

from .models import (
    TaskCategory,
    TaskKind,
    TaskStatus,
    TaskTemplate,
    TaskTemplateStep,
)

REFERENCE_AT_END = re.compile(r"\(([^()]+)\)\s*$")


def client_label(client: Client) -> str:
    return f"{client.name} ({client.reference})" if client.reference else client.name


def resolve_client(text: str) -> Client | None:
    """Find the client a person typed or picked: “Name (REF)”, a number, or an exact name."""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        found = Client.objects.filter(pk=int(text)).first()
        if found:
            return found
    match = REFERENCE_AT_END.search(text)
    if match:
        found = Client.objects.filter(reference__iexact=match.group(1).strip()).first()
        if found:
            return found
    matches = list(Client.objects.filter(name__iexact=text)[:2])
    if len(matches) == 1:
        return matches[0]
    raise ValidationError("Choose a client from the list, or leave this empty.")


class StaffChoiceField(forms.ModelChoiceField):
    def __init__(self, **kwargs):
        kwargs.setdefault("queryset", User.objects.staff().filter(is_active=True))
        super().__init__(**kwargs)


class TaskCreateForm(StyledFormMixin, forms.Form):
    title = forms.CharField(max_length=250)
    client_text = forms.CharField(
        required=False,
        label="Client",
        widget=forms.TextInput(
            attrs={
                "list": "client-options",
                "autocomplete": "off",
                "hx-get": reverse_lazy("tasks:client_options"),
                "hx-trigger": "input changed delay:250ms",
                "hx-target": "#client-options",
                "hx-swap": "innerHTML",
            }
        ),
        help_text="Start typing a name or number. Leave empty for the practice's own work.",
    )
    kind = forms.ChoiceField(choices=TaskKind.choices, initial=TaskKind.ADVISORY, label="Kind")
    category = forms.ModelChoiceField(TaskCategory.objects.none(), required=False)
    owner = StaffChoiceField(required=False, empty_label="Unassigned")
    target_date = forms.DateField(
        required=False, widget=DateInput, help_text="When the practice plans to finish."
    )
    due_date = forms.DateField(
        required=False, widget=DateInput, help_text="A hard date, such as a statutory deadline."
    )
    description = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"id": "id_description"})
    )
    status = forms.ModelChoiceField(
        TaskStatus.objects.none(), required=False, widget=forms.HiddenInput
    )
    service = forms.ModelChoiceField(
        Service.objects.none(), required=False, widget=forms.HiddenInput
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = TaskCategory.objects.filter(active=True)
        self.fields["status"].queryset = TaskStatus.objects.filter(active=True)
        self.fields["service"].queryset = Service.objects.all()
        self.fields["title"].widget.attrs["autofocus"] = True

    def clean_client_text(self):
        return resolve_client(self.cleaned_data["client_text"])


class CommentForm(StyledFormMixin, forms.Form):
    body = forms.CharField(
        label="Comment",
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Write a comment. Use @name to tell someone."}
        ),
        max_length=5000,
    )


class StatusForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaskStatus
        fields = ["name", "colour", "is_done", "is_waiting", "is_default", "active"]
        widgets = {"colour": forms.TextInput(attrs={"type": "color"})}
        labels = {"is_done": "Counts as done", "active": "In use"}

    def _get_validation_exclusions(self):
        # Saving moves the default over from the old status, so the one-default
        # constraint is not checked against the old row here.
        return super()._get_validation_exclusions() | {"is_default"}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if TaskStatus.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("There is already a status with this name.")
        return name

    def clean(self):
        data = super().clean()
        if data.get("is_default") and (data.get("is_done") or not data.get("active", True)):
            raise ValidationError("New tasks cannot start in a done or switched-off status.")
        if self.instance.pk and self.instance.is_default and not data.get("is_default"):
            raise ValidationError("Choose another status as the default instead.")
        if (
            self.instance.pk
            and self.instance.is_done
            and (not data.get("is_done") or not data.get("active", True))
            and not TaskStatus.objects.filter(is_done=True, active=True)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise ValidationError("There must be at least one done status.")
        return data

    def save(self, commit=True):
        status = super().save(commit=False)
        if commit:
            if status.is_default:
                TaskStatus.objects.exclude(pk=status.pk).update(is_default=False)
            status.save()
        return status


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaskCategory
        fields = ["name", "kind", "colour", "active"]
        widgets = {"colour": forms.TextInput(attrs={"type": "color"})}
        labels = {"active": "In use"}

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if TaskCategory.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("There is already a category with this name.")
        return name

    def clean_colour(self):
        validate_hex_colour(self.cleaned_data["colour"])
        return self.cleaned_data["colour"]


class MergeForm(StyledFormMixin, forms.Form):
    into = forms.ModelChoiceField(queryset=None, label="Move everything to")

    def __init__(self, *args, queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["into"].queryset = queryset


class TemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = [
            "rule",
            "name_pattern",
            "category",
            "default_owner",
            "owner_user",
            "target_kind",
            "target_days",
            "target_month",
            "target_day",
            "estimate_minutes",
            "active",
        ]
        labels = {
            "rule": "Deadline rule that creates it",
            "target_days": "Number of days",
            "target_month": "Month (1 to 12)",
            "target_day": "Day of the month",
            "estimate_minutes": "Estimate in minutes",
        }

    def __init__(self, *args, service, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = service
        self.instance.service = service
        self.fields["rule"] = forms.ChoiceField(
            choices=[(r, r) for r in service.rules], label="Deadline rule that creates it"
        )
        self.fields["rule"].widget.attrs["class"] = "select"
        self.fields["category"].queryset = TaskCategory.objects.filter(active=True)
        self.fields["owner_user"].queryset = User.objects.staff().filter(is_active=True)
        self.fields["owner_user"].label = "Named person"

    def clean_name_pattern(self):
        pattern = self.cleaned_data["name_pattern"].strip()
        try:
            pattern.format(period_end="", period_label="", due_date="")
        except (KeyError, IndexError, ValueError) as error:
            raise ValidationError(
                "Use only {period_end}, {period_label} and {due_date} in the name."
            ) from error
        return pattern

    def clean(self):
        data = super().clean()
        if data.get("target_kind") == TaskTemplate.Target.FIXED_DAY:
            month, day = data.get("target_month"), data.get("target_day")
            if not (month and day and 1 <= month <= 12 and 1 <= day <= 31):
                raise ValidationError("Give the month (1 to 12) and the day for a fixed date.")
        if data.get("default_owner") == TaskTemplate.Owner.USER and not data.get("owner_user"):
            raise ValidationError("Choose the person who owns these tasks.")
        return data


class StepForm(forms.ModelForm):
    class Meta:
        model = TaskTemplateStep
        fields = ["name", "position", "stops_reminders", "is_filing"]
        labels = {
            "stops_reminders": "Stops reminders",
            "is_filing": "Filing step",
        }


StepFormSet = forms.inlineformset_factory(
    TaskTemplate, TaskTemplateStep, form=StepForm, extra=2, can_delete=True
)


class TaskDescriptionForm(forms.Form):
    description = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"id": "id_description"})
    )
