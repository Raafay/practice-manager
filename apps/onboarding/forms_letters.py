from django import forms

from apps.core.forms import StyledFormMixin

from .models import LetterPart


class LetterForm(StyledFormMixin, forms.Form):
    signer = forms.ModelChoiceField(queryset=None, label="Who signs")
    body_html = forms.CharField(widget=forms.HiddenInput, label="Letter")

    def __init__(self, *args, signers, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["signer"].queryset = signers
        self.fields["signer"].label_from_instance = lambda c: f"{c.full_name} ({c.email})"


class SignForm(StyledFormMixin, forms.Form):
    agree = forms.BooleanField(required=False, label="I have read and agree to this letter")
    typed_name = forms.CharField(max_length=200, label="Type your full name", required=False)


class LetterPartForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LetterPart
        fields = ["body"]
        widgets = {"body": forms.HiddenInput}
