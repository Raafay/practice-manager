from django import forms

from apps.accounts.models import User
from apps.clients.forms import staff_choices
from apps.clients.models import Client
from apps.core.forms import StyledFormMixin


class AddCompanyForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(
        choices=[
            (Client.Status.ACTIVE, "Active"),
            (Client.Status.ONBOARDING, "Onboarding"),
            (Client.Status.PROSPECT, "Prospect"),
        ],
        initial=Client.Status.ACTIVE,
    )
    manager = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, empty_label="Nobody yet"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = staff_choices()
