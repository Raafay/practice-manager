from datetime import date, datetime

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.forms import staff_choices
from apps.clients.models import Client
from apps.comms.forms import ComposeForm
from apps.core.forms import DateInput, StyledFormMixin
from apps.core.html import clean_html

from .models import Meeting, PipelineSettings, PipelineStage, ProspectDetails

SOURCE_CHOICES = [("", "Any source"), *Client.Source.choices]


class ProspectFilterForm(StyledFormMixin, forms.Form):
    owner = forms.ChoiceField(required=False, label="Owner")
    stage = forms.ChoiceField(required=False, label="Stage")
    source = forms.ChoiceField(required=False, choices=SOURCE_CHOICES, label="Source")
    quiet = forms.BooleanField(required=False, label="Quiet only")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].choices = [
            ("", "Anyone"),
            ("none", "Nobody"),
            *[(str(u.pk), u.name) for u in staff_choices()],
        ]
        self.fields["stage"].choices = [("", "Any stage")] + [
            (str(s.pk), s.name) for s in PipelineStage.objects.all()
        ]

    def filters(self) -> dict:
        if not self.is_valid():
            return {}
        return {k: v for k, v in self.cleaned_data.items() if v}


class NewProspectForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=200, label="Name of the prospect")
    client_type = forms.ChoiceField(
        choices=Client.Type.choices, initial=Client.Type.LTD, label="Type"
    )
    first_name = forms.CharField(max_length=100, required=False, label="Main contact: first name")
    last_name = forms.CharField(max_length=100, required=False, label="Main contact: last name")
    email = forms.EmailField(required=False, label="Main contact: email")
    phone = forms.CharField(max_length=40, required=False, label="Main contact: phone")
    source = forms.ChoiceField(required=False, choices=[("", "Not known"), *Client.Source.choices])
    referred_by_client = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Referred by (a client)"
    )
    referred_by_text = forms.CharField(
        max_length=200, required=False, label="Referred by (someone else)"
    )
    owner = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    expected_fee = forms.DecimalField(
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        label="Expected monthly fee (£, excluding VAT)",
        help_text="Used only until services are ticked.",
    )
    next_action = forms.CharField(max_length=250, required=False, label="Next action")
    next_action_date = forms.DateField(required=False, widget=DateInput, label="Next action date")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, can_fees=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = staff_choices()
        self.fields["referred_by_client"].queryset = Client.objects.not_archived().order_by("name")
        if not can_fees:
            del self.fields["expected_fee"]

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first_name"), cleaned.get("last_name")
        if bool(first) != bool(last):
            raise ValidationError("Give both the first and last name of the contact, or neither.")
        if not (cleaned.get("email") or cleaned.get("phone")):
            raise ValidationError("Give an email address or a phone number to reach the contact.")
        return cleaned


class SalesForm(StyledFormMixin, forms.ModelForm):
    source = forms.ChoiceField(required=False, choices=[("", "Not known"), *Client.Source.choices])
    referred_by_client = forms.ModelChoiceField(
        queryset=Client.objects.none(), required=False, label="Referred by (a client)"
    )
    referred_by_text = forms.CharField(
        max_length=200, required=False, label="Referred by (someone else)"
    )
    expected_start = forms.DateField(
        required=False,
        widget=DateInput,
        label="Expected start",
        help_text="Any day in the month; only the month is used.",
    )

    class Meta:
        model = ProspectDetails
        fields = [
            "owner",
            "enquiry_date",
            "expected_start",
            "expected_fee",
            "setup_fee",
            "next_action",
            "next_action_date",
        ]
        widgets = {"enquiry_date": DateInput, "next_action_date": DateInput}

    def __init__(self, *args, client, can_fees=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.fields["owner"].queryset = staff_choices()
        self.fields["source"].initial = client.source
        self.fields["referred_by_client"].queryset = (
            Client.objects.not_archived().exclude(pk=client.pk).order_by("name")
        )
        self.fields["referred_by_client"].initial = client.referred_by_client_id
        self.fields["referred_by_text"].initial = client.referred_by_text
        if not can_fees:
            del self.fields["expected_fee"], self.fields["setup_fee"]

    def clean_expected_start(self):
        value = self.cleaned_data.get("expected_start")
        return value.replace(day=1) if value else None


class MoveForm(StyledFormMixin, forms.Form):
    lost_reason = forms.ChoiceField(
        choices=[("", "Choose a reason"), *ProspectDetails.LostReason.choices],
        label="Why was it lost?",
    )
    lost_note = forms.CharField(max_length=300, required=False, label="A note (optional)")


class MeetingForm(StyledFormMixin, forms.Form):
    on_date = forms.DateField(widget=DateInput, label="Date")
    at_time = forms.TimeField(
        widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"), label="Time"
    )
    kind = forms.ChoiceField(choices=Meeting.Kind.choices, label="Type")
    place = forms.CharField(max_length=200, required=False)
    staff = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )
    people = forms.CharField(max_length=300, required=False, label="People from the client")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    outcome = forms.CharField(max_length=300, required=False)
    follow_up = forms.CharField(
        max_length=300,
        required=False,
        label="Follow-up",
        help_text="Saving a follow-up makes a sales task for the prospect's owner.",
    )
    follow_up_date = forms.DateField(required=False, widget=DateInput, label="Follow-up date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["staff"].queryset = staff_choices()
        self.fields["at_time"].widget.format = "%H:%M"

    def held_at(self) -> datetime:
        return timezone.make_aware(
            datetime.combine(self.cleaned_data["on_date"], self.cleaned_data["at_time"]),
            timezone.get_current_timezone(),
        )


class ProposalComposeForm(ComposeForm):
    show_breakdown = forms.BooleanField(required=False, label="Show breakdown of fees")
    show_inc_vat = forms.BooleanField(required=False, label="Show fees including VAT")
    show_vat_text = forms.BooleanField(required=False, label="Show VAT wording")

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, client=client, **kwargs)
        for name in ("template", "bcc", "upload"):
            del self.fields[name]
        self.fields["to"].required = False


class AcceptForm(StyledFormMixin, forms.Form):
    agree = forms.BooleanField(
        label="I accept this proposal",
        error_messages={"required": "Tick the box to say you accept this proposal."},
    )
    typed_name = forms.CharField(
        max_length=200,
        label="Type your full name",
        error_messages={"required": "Type your full name."},
    )


class DeclineForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        max_length=500,
        required=False,
        label="Why not? (optional)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class QuestionForm(StyledFormMixin, forms.Form):
    question = forms.CharField(
        max_length=2000,
        label="Your question",
        widget=forms.Textarea(attrs={"rows": 4}),
        error_messages={"required": "Write your question."},
    )


class StageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineStage
        fields = ["name", "chance", "colour", "position"]
        widgets = {"colour": forms.TextInput(attrs={"type": "color"})}
        labels = {"position": "Order (lowest first)"}

    def clean_colour(self):
        import re

        value = self.cleaned_data["colour"]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValidationError("Choose a colour.")
        return value.lower()


class PipelineSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PipelineSettings
        fields = ["quiet_days", "valid_days", "opening_text", "what_next_html"]
        widgets = {
            "opening_text": forms.Textarea(attrs={"rows": 3}),
            "what_next_html": forms.HiddenInput(),
        }
        labels = {"opening_text": "Opening text on proposals"}

    def clean_what_next_html(self):
        return clean_html(self.cleaned_data.get("what_next_html", ""))

    def save(self, commit=True):
        row = super().save(commit=False)
        row.wording_is_starter = False
        if commit:
            row.save()
        return row


def today() -> date:
    return timezone.localdate()
