from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from apps.clients.models import Client
from apps.core.forms import DateInput, StyledFormMixin, widget_css

from . import services
from .models import ClientService, Service
from .rules import REGISTRY

MONTHS = [(i, name) for i, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)]  # fmt: skip


class ServiceForm(StyledFormMixin, forms.ModelForm):
    applies_to = forms.MultipleChoiceField(
        choices=Client.Type.choices,
        widget=forms.CheckboxSelectMultiple,
        label="Applies to",
    )
    rules = forms.MultipleChoiceField(
        required=False,
        choices=[],
        widget=forms.CheckboxSelectMultiple,
        label="Deadline rules",
        help_text="Each rule creates its own recurring deadlines. Rules are listed in the spec.",
    )

    class Meta:
        model = Service
        fields = [
            "name",
            "code",
            "kind",
            "applies_to",
            "default_fee",
            "description",
            "schedule_text",
            "rules",
            "renewal",
            "active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "schedule_text": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rules"].choices = [(k, f"{v.title} ({k})") for k, v in REGISTRY.items()]
        self.fields["code"].required = False
        self.fields["code"].help_text = "Short name used in reports. Leave blank to make one."
        if self.instance.pk:
            self.fields["code"].disabled = True

    def clean_code(self):
        if self.instance.pk:
            return self.instance.code
        code = slugify(self.cleaned_data.get("code") or self.data.get("name", ""))[:40]
        if not code:
            raise ValidationError("Enter a name for the service.")
        if Service.objects.filter(code=code).exists():
            raise ValidationError("There is already a service with this code.")
        return code

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        clash = Service.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise ValidationError("There is already a service with this name.")
        return name

    def save(self, commit=True):
        service = super().save(commit=False)
        if not service.pk:
            service.position = (
                Service.objects.order_by("-position").first() or Service(position=0)
            ).position + 10
        if commit:
            service.save()
        return service


class ClientServiceForm(StyledFormMixin, forms.Form):
    """Switch a service on for a client, or change its start date, fee and settings.

    The fields after the fee depend on the service: VAT and payroll write to the
    client record (where the dates are already held); regular work, renewals and
    quarterly updates keep their settings on the client service.
    """

    def __init__(self, *args, client: Client, service: Service, user, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.client, self.service, self.user, self.instance = client, service, user, instance
        self.kind = services.settings_kind(service)
        self.pre_live = client.status in services.PRE_LIVE
        current = (instance.settings if instance else services.default_settings(service)) or {}

        if not self.pre_live:
            self.fields["starts_on"] = forms.DateField(
                label="Starts on",
                widget=DateInput(),
                initial=(instance.starts_on if instance else None) or timezone.localdate(),
            )
        self.has_fee = user.can("fees.view")
        if self.has_fee:
            amount = instance.fee_amount if instance else service.default_fee
            self.fields["fee_amount"] = forms.DecimalField(
                label="Fee (£, excluding VAT)",
                required=False,
                max_digits=10,
                decimal_places=2,
                min_value=0,
                initial=amount,
            )
            self.fields["fee_frequency"] = forms.ChoiceField(
                label="Charged",
                choices=ClientService.Frequency.choices,
                initial=instance.fee_frequency if instance else "monthly",
            )
            if instance:
                self.fields["fee_reason"] = forms.CharField(
                    label="Reason for a fee change", required=False, max_length=300
                )
        getattr(self, f"_add_{self.kind or 'none'}")(current)
        self.fields["notes"] = forms.CharField(
            label="Notes",
            required=False,
            widget=forms.Textarea(attrs={"rows": 2}),
            initial=instance.notes if instance else "",
            help_text="For example, that tax is paid by instalments.",
        )
        for field in self.fields.values():  # the mixin ran before these fields existed
            if "class" not in field.widget.attrs:
                field.widget.attrs["class"] = widget_css(field.widget)

    # ---- the settings that belong to each kind of service

    def _add_none(self, current):
        pass

    def _client_field(self, name, **overrides):
        model_field = Client._meta.get_field(name)
        field = model_field.formfield(**overrides)
        field.initial = getattr(self.client, name)
        field.required = False
        self.fields[name] = field

    def _add_vat(self, current):
        for name in ("vat_frequency", "vat_stagger", "vat_scheme", "vat_year_end_month"):
            self._client_field(name)
        self.fields[
            "vat_year_end_month"
        ].help_text = "Needed only for the annual accounting scheme."
        self.client_fields = ["vat_frequency", "vat_stagger", "vat_scheme", "vat_year_end_month"]

    def _add_payroll(self, current):
        names = ["payroll_frequency", "pay_day_rule", "pay_day", "first_pay_date"]
        for name in names:
            self._client_field(name)
        self.fields["first_pay_date"].widget = DateInput()
        self.fields[
            "pay_day"
        ].help_text = "A day of the month; a day the month lacks means its last day."
        self.fields["paye_quarterly"] = forms.BooleanField(
            required=False,
            initial=bool(current.get("paye_quarterly")),
            label="Pays PAYE quarterly (small employer)",
        )
        self.client_fields = names

    def _add_periodic(self, current):
        if self.service.renewal:
            initial = None
            if current.get("end_month") and current.get("end_day"):
                year = timezone.localdate().year
                initial = date(year, int(current["end_month"]), int(current["end_day"]))
            self.fields["renewal_date"] = forms.DateField(
                label="Renewal date", widget=DateInput(), initial=initial
            )
            return
        self.fields["frequency"] = forms.ChoiceField(
            label="How often",
            choices=[("monthly", "Monthly"), ("quarterly", "Quarterly"), ("annual", "Annual")],
            initial=current.get("frequency", "monthly"),
        )
        self.fields["end_month"] = forms.TypedChoiceField(
            label="A period ends in (month)",
            choices=MONTHS,
            coerce=int,
            initial=current.get("end_month", 12),
            help_text="For quarterly and annual work. Quarters fall every three months from it.",
        )
        self.fields["end_day"] = forms.IntegerField(
            label="Period ends on day",
            required=False,
            min_value=1,
            max_value=31,
            initial=current.get("end_day"),
            help_text="Blank means the last day of the month.",
        )
        self.fields["due_days"] = forms.IntegerField(
            label="Due (days after the period ends)",
            min_value=0,
            max_value=365,
            initial=current.get("due_days", 14),
        )

    def _add_mtd(self, current):
        self._client_field("mtd_start")
        self.client_fields = ["mtd_start"]
        self.fields["calendar_quarters"] = forms.BooleanField(
            required=False,
            initial=bool(current.get("calendar_quarters")),
            label="Uses calendar quarters (the dates stay the same)",
        )

    # ---- saving

    def clean(self):
        data = super().clean()
        annual = data.get("vat_scheme") == "annual_accounting"
        if self.kind == "vat" and annual and not data.get("vat_year_end_month"):
            self.add_error("vat_year_end_month", "Choose the month the VAT year ends.")
        if self.kind == "payroll":
            if data.get("payroll_frequency") == "monthly" and not data.get("pay_day_rule"):
                self.add_error("pay_day_rule", "Choose how the pay day is worked out.")
            if data.get("pay_day_rule") == "day_of_month" and not data.get("pay_day"):
                self.add_error("pay_day", "Enter the day of the month.")
            if data.get("payroll_frequency") in (
                "weekly",
                "fortnightly",
                "four_weekly",
            ) and not data.get("first_pay_date"):
                self.add_error("first_pay_date", "Enter the first pay date.")
        return data

    def service_settings(self) -> dict:
        data = self.cleaned_data
        current = dict((self.instance.settings if self.instance else None) or {})
        if self.kind == "payroll":
            current["paye_quarterly"] = bool(data.get("paye_quarterly"))
        elif self.kind == "mtd":
            current["calendar_quarters"] = bool(data.get("calendar_quarters"))
        elif self.kind == "periodic":
            if self.service.renewal:
                renewal = data["renewal_date"]
                current.update(
                    frequency="annual",
                    end_month=renewal.month,
                    end_day=renewal.day,
                    due_days=0,
                    renewal=True,
                )
            else:
                current.update(
                    frequency=data["frequency"],
                    end_month=data["end_month"],
                    end_day=data.get("end_day"),
                    due_days=data["due_days"],
                )
        return current

    def save(self, actor) -> ClientService:
        data = self.cleaned_data
        client_values = {n: data.get(n) for n in getattr(self, "client_fields", [])}
        if client_values:
            services.update_client_fields(
                actor, self.client, _blank_for_null(client_values), section=self.service.name
            )
        settings = self.service_settings()
        if self.instance is None:
            return services.switch_on(
                actor,
                self.client,
                self.service,
                starts_on=data.get("starts_on"),
                fee_amount=data.get("fee_amount") if self.has_fee else None,
                fee_frequency=data.get("fee_frequency") or "monthly",
                settings=settings,
                notes=data.get("notes", ""),
            )
        cs = self.instance
        services.update_service(
            actor,
            cs,
            starts_on=data.get("starts_on"),
            settings=settings,
            notes=data.get("notes", ""),
        )
        if self.has_fee:
            services.change_fee(
                actor,
                cs,
                data.get("fee_amount"),
                data["fee_frequency"],
                reason=data.get("fee_reason", ""),
            )
        return cs


def _blank_for_null(values: dict) -> dict:
    """Text choice fields store "" for nothing; numbers and dates store None."""
    cleaned = {}
    for name, value in values.items():
        field = Client._meta.get_field(name)
        if value in (None, "") and not field.null:
            value = ""
        elif value == "":
            value = None
        cleaned[name] = value
    return cleaned


class EndServiceForm(StyledFormMixin, forms.Form):
    ends_on = forms.DateField(label="Ends on", widget=DateInput())
    reason = forms.CharField(label="Reason", required=False, max_length=300)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ends_on"].initial = timezone.localdate()


class DoneForm(StyledFormMixin, forms.Form):
    done_on = forms.DateField(label="Done on", widget=DateInput())
    note = forms.CharField(label="Note", required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["done_on"].initial = timezone.localdate()

    def clean_done_on(self):
        value = self.cleaned_data["done_on"]
        if value > timezone.localdate():
            raise ValidationError("A deadline cannot be done in the future.")
        return value


class ConfirmForm(forms.Form):
    """A confirmation with no fields."""


class ReasonForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(label="Reason", max_length=300)


class ChangeDateForm(StyledFormMixin, forms.Form):
    due_date = forms.DateField(label="New due date", widget=DateInput())
    reason = forms.CharField(label="Reason", max_length=300)


class DeadlineFilterForm(StyledFormMixin, forms.Form):
    WITHIN = [("", "Any time"), ("14", "Within 14 days"), ("30", "Within 30 days"),
              ("60", "Within 60 days"), ("90", "Within 90 days")]  # fmt: skip

    within = forms.ChoiceField(required=False, choices=WITHIN, label="Due")
    overdue = forms.BooleanField(required=False, label="Overdue only")
    service = forms.ModelChoiceField(
        queryset=Service.objects.none(), required=False, empty_label="Any service"
    )
    manager = forms.ModelChoiceField(queryset=None, required=False, empty_label="Anyone")
    client = forms.CharField(required=False, label="Client", max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User

        self.fields["service"].queryset = Service.objects.all()
        self.fields["manager"].queryset = User.objects.staff().order_by("name")
