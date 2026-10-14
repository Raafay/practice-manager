from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.clients.models import Client
from apps.core.forms import DateInput, StyledFormMixin
from apps.services.models import Service
from apps.tasks.models import Task

from . import services


class TimeEntryForm(StyledFormMixin, forms.Form):
    client = forms.ModelChoiceField(
        Client.objects.none(), required=False, label="Client", empty_label="Internal (no client)"
    )
    service = forms.ModelChoiceField(
        Service.objects.filter(active=True), required=False, label="Service", empty_label="None"
    )
    task = forms.ModelChoiceField(Task.objects.none(), required=False, widget=forms.HiddenInput)
    date = forms.DateField(widget=DateInput, label="Date")
    duration = forms.CharField(
        max_length=20, label="Time", help_text="Hours and minutes, such as 1:30, 1.5 or 45m."
    )
    note = forms.CharField(max_length=300, required=False, label="Note")
    billable = forms.BooleanField(required=False, initial=True, label="Billable")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = (
            Client.objects.not_archived().exclude(status__in=(Client.Status.LOST,)).order_by("name")
        )
        self.fields["task"].queryset = Task.objects.all()
        self.fields.setdefault("date", self.fields["date"])
        self.fields["date"].initial = timezone.localdate

    def clean_duration(self):
        return services.parse_duration(self.cleaned_data["duration"])

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value > timezone.localdate():
            raise ValidationError("Time cannot be logged for a day that has not happened.")
        return value
