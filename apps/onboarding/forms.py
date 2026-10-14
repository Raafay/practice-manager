from django import forms

from apps.core.forms import DateInput, StyledFormMixin

from .models import AgentAuthorisation, ChecklistTemplateItem, ClearanceRequest, OnboardingItem


class ItemForm(StyledFormMixin, forms.Form):
    state = forms.ChoiceField(choices=OnboardingItem.State.choices)
    note = forms.CharField(required=False, max_length=300)


class MakeLiveForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(
        required=False,
        max_length=300,
        label="Reason for making the client live early",
        help_text="Needed only when items are still open. It is logged as an override.",
    )


class ChecklistTemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ChecklistTemplateItem
        fields = ["name", "needed_before_golive", "position", "active"]
        labels = {"position": "Order"}

    def save(self, commit=True):
        item = super().save(commit=False)
        if not item.key:
            from django.utils.text import slugify

            base = slugify(item.name)[:30] or "item"
            key, n = base, 1
            while ChecklistTemplateItem.objects.filter(key=key).exists():
                n += 1
                key = f"{base}-{n}"
            item.key = key
        if commit:
            item.save()
        return item


class AuthorisationAddForm(StyledFormMixin, forms.Form):
    tax = forms.ChoiceField(choices=AgentAuthorisation.Tax.choices)
    method = forms.ChoiceField(choices=AgentAuthorisation.Method.choices)
    contact = forms.ModelChoiceField(
        queryset=None, required=False, help_text="For personal taxes: whose authorisation."
    )

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.clients.models import Contact

        self.fields["contact"].queryset = Contact.objects.filter(client_links__client=client)


class AuthorisationForm(StyledFormMixin, forms.Form):
    state = forms.ChoiceField(choices=AgentAuthorisation.State.choices)
    method = forms.ChoiceField(choices=AgentAuthorisation.Method.choices)
    contact = forms.ModelChoiceField(queryset=None, required=False)
    requested_on = forms.DateField(required=False, widget=DateInput)
    code = forms.CharField(
        required=False,
        max_length=60,
        label="HMRC code",
        help_text="Leave blank to keep the saved code. It is stored encrypted.",
    )
    clear_code = forms.BooleanField(required=False, label="Remove the saved code")
    code_received_on = forms.DateField(required=False, widget=DateInput)
    code_expires_on = forms.DateField(
        required=False,
        widget=DateInput,
        help_text="A postal code is taken to expire 30 days after it is issued. Edit if needed.",
    )
    link_sent_on = forms.DateField(required=False, widget=DateInput)
    link_expires_on = forms.DateField(
        required=False,
        widget=DateInput,
        help_text="A handshake link expires 21 days after it is sent.",
    )
    authorised_on = forms.DateField(required=False, widget=DateInput)
    notes = forms.CharField(required=False, max_length=300)

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.clients.models import Contact

        self.fields["contact"].queryset = Contact.objects.filter(client_links__client=client)

    @classmethod
    def for_instance(cls, auth):
        initial = {
            name: getattr(auth, name)
            for name in (
                "state",
                "method",
                "requested_on",
                "code_received_on",
                "code_expires_on",
                "link_sent_on",
                "link_expires_on",
                "authorised_on",
                "notes",
            )
        }
        initial["contact"] = auth.contact_id
        return cls(initial=initial, client=auth.client)


class ClearanceForm(StyledFormMixin, forms.Form):
    accountant_name = forms.CharField(max_length=150, label="Previous accountant")
    firm = forms.CharField(max_length=200, required=False)
    email = forms.EmailField()
    asked_for = forms.MultipleChoiceField(
        choices=ClearanceRequest.ITEMS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="What to ask for",
        initial=[k for k, _ in ClearanceRequest.ITEMS],
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class ClearanceUpdateForm(StyledFormMixin, forms.Form):
    received = forms.MultipleChoiceField(
        choices=ClearanceRequest.ITEMS,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="What has arrived",
    )
    reply_received_on = forms.DateField(required=False, widget=DateInput)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
