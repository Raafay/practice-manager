from django import forms

from apps.core.forms import StyledFormMixin

from .models import FinanceSettings


class FinanceSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = FinanceSettings
        fields = [
            "target_hourly_rate",
            "not_invoiced_after_day",
            "default_start_days",
            "summary_weekday",
            "summary_hour",
        ]
