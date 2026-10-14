from django import forms

from apps.clients.documents import check_document_upload
from apps.clients.models import Contact
from apps.core.forms import DateInput, StyledFormMixin

from .models import AmlSettings, IdentityCheck, PolicyDocument, RiskQuestion, TrainingRecord


class IdentityCheckForm(StyledFormMixin, forms.Form):
    state = forms.ChoiceField(choices=IdentityCheck.State.choices)
    method = forms.ChoiceField(
        choices=[("", "---------"), *IdentityCheck.Method.choices], required=False
    )
    document_type = forms.ChoiceField(
        choices=[("", "---------"), *IdentityCheck.DocType.choices], required=False
    )
    document_expiry = forms.DateField(
        required=False,
        widget=DateInput,
        help_text="You are reminded 60 days before. The check does not lapse by itself.",
    )
    proof_of_address = forms.ChoiceField(
        choices=[("", "---------"), *IdentityCheck.AddressProof.choices],
        required=False,
        label="Proof of address type",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    id_file = forms.FileField(
        required=False,
        label="Upload identity document",
        help_text="Stored as a sensitive document. Each view is logged. Do not type the number.",
    )
    address_file = forms.FileField(required=False, label="Upload proof of address")

    def clean_id_file(self):
        return self._check(self.cleaned_data.get("id_file"))

    def clean_address_file(self):
        return self._check(self.cleaned_data.get("address_file"))

    @staticmethod
    def _check(upload):
        if upload:
            check_document_upload(upload)
        return upload


class ReasonForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=300)


class PersonAddForm(StyledFormMixin, forms.Form):
    contact = forms.ModelChoiceField(queryset=Contact.objects.none(), label="Person")
    reason = forms.CharField(max_length=300)

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].queryset = Contact.objects.filter(client_links__client=client)


class SendBackForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=300, label="What needs changing")


class RiskQuestionForm(StyledFormMixin, forms.Form):
    section = forms.CharField(max_length=80)
    text = forms.CharField(max_length=300, label="Question")
    help_text = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    answer_type = forms.ChoiceField(choices=RiskQuestion.AnswerType.choices)
    yes_score = forms.IntegerField(min_value=0, max_value=50, initial=0, label="Score for Yes")
    no_score = forms.IntegerField(min_value=0, max_value=50, initial=0, label="Score for No")
    enhanced_on = forms.ChoiceField(
        choices=[
            ("", "Never"),
            ("yes", "Yes means enhanced checks"),
            ("no", "No means enhanced checks"),
        ],
        required=False,
        label="Enhanced checks",
    )
    choices = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label="Choices (for a choice question)",
        help_text="One per line: label | score | enhanced (write enhanced to flag it).",
    )
    records_check = forms.BooleanField(required=False, label="Record the date checked and how")
    position = forms.IntegerField(min_value=0, initial=0, label="Order")
    active = forms.BooleanField(required=False, initial=True)

    @classmethod
    def from_question(cls, question: RiskQuestion):
        initial = {
            "section": question.section,
            "text": question.text,
            "help_text": question.help_text,
            "answer_type": question.answer_type,
            "records_check": question.records_check,
            "position": question.position,
            "active": question.active,
        }
        if question.answer_type == "yes_no":
            for option in question.options:
                initial[f"{option['value']}_score"] = option["score"]
                if option.get("enhanced"):
                    initial["enhanced_on"] = option["value"]
        else:
            initial["choices"] = "\n".join(
                f"{o['label']} | {o['score']}" + (" | enhanced" if o.get("enhanced") else "")
                for o in question.options
            )
        return cls(initial=initial)

    def clean(self):
        data = super().clean()
        if data.get("answer_type") == "choice":
            options = []
            for number, line in enumerate((data.get("choices") or "").splitlines(), start=1):
                if not line.strip():
                    continue
                bits = [b.strip() for b in line.split("|")]
                try:
                    score = int(bits[1]) if len(bits) > 1 and bits[1] else 0
                except ValueError:
                    self.add_error("choices", f"Line {number}: the score must be a whole number.")
                    continue
                options.append(
                    {
                        "value": f"c{number}",
                        "label": bits[0][:80],
                        "score": score,
                        "enhanced": "enhanced" in [b.lower() for b in bits[2:]],
                    }
                )
            if len(options) < 2:
                self.add_error("choices", "A choice question needs at least two choices.")
            data["options"] = options
        elif data.get("answer_type") == "yes_no":
            enhanced = data.get("enhanced_on") or ""
            data["options"] = [
                {
                    "value": value,
                    "label": value.capitalize(),
                    "score": data.get(f"{value}_score") or 0,
                    "enhanced": enhanced == value,
                }
                for value in ("yes", "no")
            ]
        return data


class AmlSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AmlSettings
        fields = [
            "medium_from",
            "high_from",
            "review_months_high",
            "review_months_medium",
            "review_months_low",
            "higher_risk_services",
        ]
        widgets = {"higher_risk_services": forms.CheckboxSelectMultiple}

    def clean(self):
        data = super().clean()
        medium, high = data.get("medium_from"), data.get("high_from")
        if medium and high and high <= medium:
            self.add_error("high_from", "High must start above the medium score.")
        return data


class PracticeRecordsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AmlSettings
        fields = ["supervisory_body", "nominated_officer"]
        labels = {"supervisory_body": "Supervisory body", "nominated_officer": "Nominated officer"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        self.fields["nominated_officer"].queryset = User.objects.staff().filter(is_active=True)


class TrainingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TrainingRecord
        fields = ["person", "trained_on", "course", "notes"]
        widgets = {"trained_on": DateInput}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        self.fields["person"].queryset = User.objects.staff().filter(is_active=True)


class PolicyDocumentForm(StyledFormMixin, forms.Form):
    title = forms.CharField(max_length=200)
    file = forms.FileField()

    def clean_file(self):
        upload = self.cleaned_data["file"]
        self.content_type = check_document_upload(upload)
        return upload


__all__ = [n for n in dir() if n.endswith("Form")] + ["PolicyDocument"]
