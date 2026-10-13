import re

from django import forms
from django.core.exceptions import ValidationError
from django.forms import modelform_factory

from apps.accounts.models import Team, User
from apps.core.fields import EncryptedTextField, mask
from apps.core.forms import DateInput, StyledFormMixin
from apps.events.services import snapshot

from . import panels
from .documents import ALLOWED_EXTENSIONS
from .models import (
    Client,
    ClientContact,
    ClientLink,
    Contact,
    CustomFieldDefinition,
    Document,
    SavedView,
    Tag,
)

NI_NUMBER = re.compile(r"^[A-Z]{2}[0-9]{6}[A-D]$")
UTR = re.compile(r"^[0-9]{10}$")
COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{6,8}$")
CH_CODE = re.compile(r"^[A-Z0-9]{6}$")

ENCRYPTED_CLEANERS = {
    "ni_number": (NI_NUMBER, "Enter a National Insurance number such as QQ123456C."),
    "personal_utr": (UTR, "A UTR is ten digits."),
    "company_utr": (UTR, "A UTR is ten digits."),
    "ch_auth_code": (CH_CODE, "A Companies House authentication code is six letters or digits."),
    "ch_personal_code": (CH_CODE, "A Companies House personal code is six letters or digits."),
}


def staff_choices():
    return User.objects.staff().filter(is_active=True).order_by("name")


class TrackedModelForm(StyledFormMixin, forms.ModelForm):
    """A model form that remembers the values before saving so the change can be logged,
    and treats encrypted fields as write-only: blank means keep, with a tick box to remove."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encrypted = [
            name
            for name in self.fields
            if isinstance(self._meta.model._meta.get_field(name), EncryptedTextField)
        ]
        for name in self.encrypted:
            current = getattr(self.instance, name, "") if self.instance.pk else ""
            model_field = self._meta.model._meta.get_field(name)
            self.initial[name] = ""  # the saved value must never be written into the page
            self.fields[name] = forms.CharField(
                label=panels.pretty_label(model_field.verbose_name),
                required=False,
                widget=forms.TextInput(
                    attrs={
                        "class": "input",
                        "autocomplete": "off",
                        "placeholder": f"Saved: {mask(current)}. Leave blank to keep."
                        if current
                        else "",
                    }
                ),
            )
            if current:
                self.fields[f"clear_{name}"] = forms.BooleanField(
                    required=False,
                    label=f"Remove the saved {str(model_field.verbose_name).lower()}",
                    widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
                )
        for field in self.fields.values():
            if field.label:
                field.label = panels.pretty_label(field.label)
        self.before = snapshot(self.instance, self._tracked()) if self.instance.pk else {}

    def _tracked(self) -> list[str]:
        return [
            n for n in self.fields if n in {f.name for f in self._meta.model._meta.get_fields()}
        ]

    def after(self) -> dict:
        return snapshot(self.instance, self._tracked())

    def clean(self):
        cleaned = super().clean()
        for name in self.encrypted:
            current = getattr(self.instance, name, "") or ""
            if cleaned.get(f"clear_{name}"):
                cleaned[name] = ""
                continue
            new = (cleaned.get(name) or "").strip().upper().replace(" ", "")
            if not new:
                cleaned[name] = current
                continue
            pattern, message = ENCRYPTED_CLEANERS[name]
            if not pattern.match(new):
                self.add_error(name, message)
            cleaned[name] = new
        return cleaned


# ------------------------------------------------------------ client panels

PANEL_WIDGETS = {
    "registered_office": forms.Textarea(attrs={"rows": 3}),
    "correspondence_address": forms.Textarea(attrs={"rows": 3}),
    "tags": forms.CheckboxSelectMultiple,
}


class ClientPanelForm(TrackedModelForm):
    panel_key = ""

    def __init__(self, *args, **kwargs):
        self.custom = (
            list(CustomFieldDefinition.objects.all()) if self.panel_key == "internal" else []
        )
        super().__init__(*args, **kwargs)
        client = self.instance
        for name in panels.COMPANIES_HOUSE_FIELDS:
            if name in self.fields and client.company_number:
                self.fields[name].disabled = True
                self.fields[name].help_text = "Comes from Companies House and cannot be changed."
        for field in self.fields.values():
            if isinstance(field.widget, forms.DateInput):
                field.widget = DateInput(attrs=field.widget.attrs)
        for name in ("partner", "manager"):
            if name in self.fields:
                self.fields[name].queryset = staff_choices()
                self.fields[name].empty_label = "Nobody"
        if "website" in self.fields:
            self.fields["website"] = forms.URLField(
                label="Website", required=False, assume_scheme="https"
            )
        for definition in self.custom:
            self.fields[f"cf_{definition.pk}"] = custom_form_field(
                definition, client.custom_values.get(str(definition.pk), "")
            )

    def _tracked(self):
        names = super()._tracked()
        return names + (["custom_values"] if self.custom else [])

    def clean_company_number(self):
        value = (self.cleaned_data.get("company_number") or "").strip().upper().replace(" ", "")
        if value and not COMPANY_NUMBER.match(value):
            raise ValidationError("A company number is six to eight letters or digits.")
        return value

    def clean_reference(self):
        value = (self.cleaned_data.get("reference") or "").strip()
        if not value:
            raise ValidationError("A client needs a reference.")
        return value

    def save(self, commit=True):
        client = super().save(commit=False)
        if self.custom:
            values = dict(client.custom_values)
            for definition in self.custom:
                raw = self.cleaned_data.get(f"cf_{definition.pk}")
                values[str(definition.pk)] = serialise_custom(definition, raw)
            client.custom_values = values
        if commit:
            client.save()
            self.save_m2m()
        return client


def custom_form_field(definition, stored: str):
    kind = CustomFieldDefinition.Kind
    common = {"label": definition.name, "required": False}
    if definition.kind == kind.NUMBER:
        field = forms.DecimalField(**common, widget=forms.NumberInput(attrs={"class": "input"}))
        initial = stored or None
    elif definition.kind == kind.DATE:
        field = forms.DateField(**common, widget=DateInput(attrs={"class": "input"}))
        initial = stored or None
    elif definition.kind == kind.YES_NO:
        field = forms.ChoiceField(
            **common,
            choices=[("", "Not set"), ("yes", "Yes"), ("no", "No")],
            widget=forms.Select(attrs={"class": "select"}),
        )
        initial = stored
    else:
        field = forms.CharField(
            **common, max_length=300, widget=forms.TextInput(attrs={"class": "input"})
        )
        initial = stored
    field.initial = initial
    return field


def serialise_custom(definition, value) -> str:
    if value in (None, ""):
        return ""
    if definition.kind == CustomFieldDefinition.Kind.DATE:
        return value.isoformat()
    return str(value)


_panel_cache: dict = {}


def panel_form_class(key: str, client: Client):
    fields = tuple(panels.panel_fields(key, client))
    cache_key = (key, fields)
    if cache_key not in _panel_cache:
        base = type("Base", (ClientPanelForm,), {"panel_key": key})
        _panel_cache[cache_key] = modelform_factory(
            Client, form=base, fields=list(fields), widgets=PANEL_WIDGETS
        )
    return _panel_cache[cache_key]


# ------------------------------------------------------------ new client


class ClientCreateForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=200)
    client_type = forms.ChoiceField(choices=Client.Type.choices, initial=Client.Type.LTD)
    manager = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Nobody yet"
    )
    first_name = forms.CharField(label="Main contact: first name", max_length=100, required=False)
    last_name = forms.CharField(label="Main contact: last name", max_length=100, required=False)
    email = forms.EmailField(label="Main contact: email", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = staff_choices()

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first_name"), cleaned.get("last_name")
        if bool(first) != bool(last):
            raise ValidationError(
                "Give both the first and last name of the main contact, or neither."
            )
        return cleaned


# ------------------------------------------------------------ people


class ContactForm(TrackedModelForm):
    class Meta:
        model = Contact
        fields = [
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "preferred_name",
            "email",
            "mobile",
            "phone",
            "date_of_birth",
            "ni_number",
            "personal_utr",
            "home_address",
            "nationality",
            "country_of_residence",
            "occupation",
            "notes",
            "ch_officer_id",
            "ch_personal_code",
            "ch_identity_verified",
            "ch_identity_verified_on",
        ]
        widgets = {
            "home_address": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "date_of_birth": DateInput,
            "ch_identity_verified_on": DateInput,
        }


class NewContactForm(TrackedModelForm):
    """The short form used when adding a person to a client."""

    class Meta:
        model = Contact
        fields = ["title", "first_name", "last_name", "email", "mobile"]


class ClientContactForm(StyledFormMixin, forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=ClientContact.Role.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ClientContact
        fields = [
            "roles",
            "is_main",
            "receives_reminders",
            "can_sign",
            "portal_access",
            "appointed_on",
            "resigned_on",
            "shareholding_percent",
        ]
        widgets = {"appointed_on": DateInput, "resigned_on": DateInput}
        help_texts = {
            "is_main": "Only one main contact per client. Choosing this replaces the current one.",
            "portal_access": "Switches on in Stage 10. It has no effect yet.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.before = snapshot(self.instance, list(self.fields)) if self.instance.pk else {}

    def after(self):
        return snapshot(self.instance, list(self.fields))


class LinkForm(StyledFormMixin, forms.Form):
    other = forms.ModelChoiceField(
        queryset=Client.objects.none(), label="Other client", widget=forms.RadioSelect
    )
    relationship = forms.ChoiceField(choices=ClientLink.Relationship.choices)
    note = forms.CharField(max_length=300, required=False)

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["other"].queryset = Client.objects.not_archived().exclude(pk=client.pk)


# ------------------------------------------------------------ status, archive, delete, notes


class StatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField()
    ended_on = forms.DateField(
        required=False,
        label="Relationship ended on",
        widget=DateInput,
        help_text="Used when the client becomes former. Sets the dates records are kept until.",
    )
    reason = forms.CharField(required=False, max_length=300, label="Reason (optional)")

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import allowed_moves

        self.fields["status"].choices = [(s, Client.Status(s).label) for s in allowed_moves(client)]


class ReasonForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=300, label="Reason")


class DeleteForm(StyledFormMixin, forms.Form):
    confirm_name = forms.CharField(label="Type the client's name to confirm")


class NoteForm(StyledFormMixin, forms.Form):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}), label="Note")
    pinned = forms.BooleanField(required=False, label="Pin to the top of the Info tab")


class CallForm(StyledFormMixin, forms.Form):
    text = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 5}), label="What was said or agreed"
    )


# ------------------------------------------------------------ documents


class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files at once (Django's documented approach)."""

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


class DocumentUploadForm(StyledFormMixin, forms.Form):
    files = MultipleFileField(
        widget=MultipleFileInput(
            attrs={"accept": ",".join(f".{e}" for e in sorted(ALLOWED_EXTENSIONS))}
        ),
        label="Files",
    )
    category = forms.ChoiceField(choices=Document.Category.choices, initial=Document.Category.OTHER)
    contact = forms.ModelChoiceField(
        queryset=Contact.objects.none(), required=False, empty_label="Not about one person"
    )
    sensitive = forms.BooleanField(
        required=False,
        label="Mark as sensitive",
        help_text="Identity and proof of address are always sensitive.",
    )

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].queryset = Contact.objects.filter(client_links__client=client)


class DocumentEditForm(TrackedModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "sensitive", "shared_with_portal"]
        help_texts = {
            "shared_with_portal": "The client portal arrives in Stage 10. This has no effect yet."
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("category") in Document.SENSITIVE_BY_DEFAULT:
            cleaned["sensitive"] = True
        return cleaned


# ------------------------------------------------------------ list, views, settings


class ClientFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.MultipleChoiceField(
        required=False, choices=Client.Status.choices, widget=forms.CheckboxSelectMultiple
    )
    client_type = forms.ChoiceField(
        required=False, choices=[("", "Any type"), *Client.Type.choices], label="Type"
    )
    manager = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Anyone"
    )
    partner = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Anyone"
    )
    team = forms.ModelChoiceField(
        queryset=Team.objects.all(), required=False, empty_label="Any team"
    )
    tag = forms.ModelChoiceField(queryset=Tag.objects.all(), required=False, empty_label="Any tag")
    archived = forms.ChoiceField(
        required=False,
        label="Archived",
        choices=[("", "Hide archived"), ("only", "Only archived")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        people = User.objects.staff().order_by("name")
        self.fields["manager"].queryset = people
        self.fields["partner"].queryset = people

    def chosen_statuses(self) -> list[str]:
        from .models import DEFAULT_LIST_STATUSES

        if self.is_valid() and self.cleaned_data.get("status"):
            return self.cleaned_data["status"]
        return list(DEFAULT_LIST_STATUSES)


class SavedViewForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SavedView
        fields = ["name", "shared"]


class UniqueNameMixin:
    """Names are unique regardless of capital letters."""

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = self._meta.model.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("There is already one with this name.")
        return name


class TagForm(UniqueNameMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Tag
        fields = ["name", "colour"]
        widgets = {"colour": forms.TextInput(attrs={"type": "color"})}


class CustomFieldForm(UniqueNameMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CustomFieldDefinition
        fields = ["name", "kind", "position"]
        labels = {"kind": "Type", "position": "Order"}
