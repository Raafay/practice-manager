from allauth.account.adapter import get_adapter
from allauth.account.forms import LoginForm
from django import forms
from django.contrib.auth import password_validation

from apps import events
from apps.core.forms import StyledFormMixin

from .models import Role, Team, User
from .rights import RIGHTS


class StaffLoginForm(LoginForm):
    """Staff sign-in. A portal account is refused with the same message as a wrong password."""

    def clean(self):
        cleaned = super().clean()
        if self.user is not None and not self.user.is_staff_kind:
            events.record(
                None,
                "auth.sign_in_failed",
                "A portal account tried the staff sign-in.",
                actor_label=self.user.email,
                request=self.request,
            )
            self.user = None
            raise get_adapter(self.request).validation_error("email_password_mismatch")
        return cleaned


class InviteForm(StyledFormMixin, forms.Form):
    name = forms.CharField(max_length=150)
    email = forms.EmailField()
    role = forms.ModelChoiceField(queryset=Role.objects.all(), empty_label=None)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Someone already has an account with this email address.")
        return email


class AcceptInvitationForm(StyledFormMixin, forms.Form):
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    password2 = forms.CharField(
        label="Password again", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def __init__(self, *args, invitation=None, **kwargs):
        self.invitation = invitation
        super().__init__(*args, **kwargs)
        self.fields["password1"].help_text = "At least 12 characters. A short sentence works well."

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get("password1"), cleaned.get("password2")
        if first and second and first != second:
            self.add_error("password2", "The two passwords do not match.")
        if first:
            probe = User(email=self.invitation.email, name=self.invitation.name)
            try:
                password_validation.validate_password(first, probe)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class RoleForm(StyledFormMixin, forms.Form):
    role = forms.ModelChoiceField(queryset=Role.objects.all(), empty_label=None)


class ExtraRightsForm(StyledFormMixin, forms.Form):
    extra_rights = forms.MultipleChoiceField(
        choices=list(RIGHTS.items()), required=False, widget=forms.CheckboxSelectMultiple
    )


class TeamsForm(StyledFormMixin, forms.Form):
    teams = forms.ModelMultipleChoiceField(
        queryset=Team.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )


class TeamForm(StyledFormMixin, forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.staff().filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Team
        fields = ["name", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["members"].initial = list(self.instance.members.all())


class RoleRightsForm(forms.Form):
    """One tick box per right for each role other than Owner."""

    def __init__(self, *args, roles=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.roles = [role for role in roles if not role.is_owner_role]
        for role in self.roles:
            for right in RIGHTS:
                self.fields[self.field_name(role, right)] = forms.BooleanField(
                    required=False, initial=right in role.rights, label=RIGHTS[right]
                )

    @staticmethod
    def field_name(role, right: str) -> str:
        return f"{role.slug}__{right}"

    def rights_for(self, role) -> list[str]:
        return [right for right in RIGHTS if self.cleaned_data.get(self.field_name(role, right))]


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = [
            "name",
            "initials",
            "colour",
            "job_title",
            "weekly_hours",
            "email_signature",
            "email_overdue",
            "email_today",
            "email_week",
        ]
        widgets = {
            "colour": forms.TextInput(attrs={"type": "color"}),
            "email_signature": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "weekly_hours": "Used to plan workload.",
            "email_overdue": "In the daily email at 08:00 on working days. Notices in the app stay on.",
        }
        labels = {
            "email_overdue": "Daily email: overdue tasks",
            "email_today": "Daily email: tasks due today",
            "email_week": "Daily email: tasks due this week",
        }

    def clean_initials(self):
        initials = self.cleaned_data["initials"].strip().upper()
        if initials and (len(initials) != 2 or not initials.isalpha()):
            raise forms.ValidationError("Use two letters.")
        return initials
