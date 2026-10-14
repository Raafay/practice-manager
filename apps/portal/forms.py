from django import forms

from apps.core.forms import StyledFormMixin


class EmailForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(
        label="Email address",
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )


class CodeForm(StyledFormMixin, forms.Form):
    code = forms.CharField(
        label="Six-digit code",
        max_length=12,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "autofocus": True,
            }
        ),
    )


class UploadForm(StyledFormMixin, forms.Form):
    category = forms.ChoiceField(label="What is it?", choices=[])
    note = forms.CharField(
        label="Note",
        max_length=200,
        required=False,
        help_text="For example, “March bank statements”.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import PORTAL_CATEGORIES

        self.fields["category"].choices = PORTAL_CATEGORIES


class PortalRequestForm(StyledFormMixin, forms.Form):
    subject = forms.CharField(label="Subject", max_length=200)
    body = forms.CharField(
        label="What do you need help with?",
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    urgency = forms.ChoiceField(
        label="How urgent is it?",
        choices=[("normal", "Normal"), ("urgent", "Urgent")],
        initial="normal",
    )


class PublicRequestForm(StyledFormMixin, forms.Form):
    """The request link. `website` is a trap for simple bots: people never see or fill it."""

    name = forms.CharField(label="Your name", max_length=150)
    email = forms.EmailField(label="Your email", max_length=254)
    phone = forms.CharField(label="Phone", max_length=40, required=False)
    body = forms.CharField(
        label="What do you need help with?",
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    urgency = forms.ChoiceField(
        label="How urgent is it?",
        choices=[("normal", "Normal"), ("urgent", "Urgent")],
        initial="normal",
    )
    website = forms.CharField(
        required=False,
        label="Leave this empty",
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["website"].widget.attrs["class"] = "hp-field"
