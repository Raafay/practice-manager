from django import forms

from apps.accounts.models import User
from apps.core.forms import StyledFormMixin

from .models import ActivityEvent


class AuditFilterForm(StyledFormMixin, forms.Form):
    person = forms.ModelChoiceField(
        queryset=User.objects.staff(), required=False, empty_label="Anyone"
    )
    verb = forms.ChoiceField(required=False, label="Action")
    date_from = forms.DateField(
        required=False, label="From", widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, label="To", widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        verbs = ActivityEvent.objects.order_by("verb").values_list("verb", flat=True).distinct()
        self.fields["verb"].choices = [("", "Any action")] + [(verb, verb) for verb in verbs]

    def filter(self, queryset):
        if not self.is_valid():
            return queryset
        data = self.cleaned_data
        if data.get("person"):
            queryset = queryset.filter(actor=data["person"])
        if data.get("verb"):
            queryset = queryset.filter(verb=data["verb"])
        if data.get("date_from"):
            queryset = queryset.filter(created_at__date__gte=data["date_from"])
        if data.get("date_to"):
            queryset = queryset.filter(created_at__date__lte=data["date_to"])
        return queryset
