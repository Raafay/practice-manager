from django import forms
from django.core.exceptions import ValidationError

from apps.clients.documents import check_document_upload
from apps.core.forms import StyledFormMixin
from apps.core.html import clean_html

from . import merge, services
from .models import Channel, MessageTemplate, ReminderSchedule, split_addresses
from .sms import sms_enabled

TRIGGER_HELP = {
    "before_deadline": "Days before the due date",
    "after_period_end": "Days after the period ends",
    "before_target": "Days before the task's target date",
    "step_ticked": "When a named step is ticked",
}


def channel_choices():
    """Text messages are offered only when a provider is configured."""
    return [(v, l) for v, l in Channel.choices if v != Channel.SMS or sms_enabled()]


class RichBodyMixin:
    """The body is a hidden box that Trix fills in. HTML is cleaned before it is kept."""

    def clean_body(self):
        value = self.cleaned_data.get("body", "")
        return clean_html(value)


class TemplateForm(StyledFormMixin, RichBodyMixin, forms.ModelForm):
    class Meta:
        model = MessageTemplate
        fields = ["name", "channel", "group", "subject", "body", "send_mode", "active"]
        widgets = {"body": forms.HiddenInput()}
        labels = {"send_mode": "When it is created", "active": "In use"}

    def __init__(self, *args, can_set_auto=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_set_auto = can_set_auto
        self.fields["channel"].choices = channel_choices()
        self.fields["body"].required = False
        if not can_set_auto:
            self.fields["send_mode"].choices = [
                (MessageTemplate.SendMode.HOLD, MessageTemplate.SendMode.HOLD.label)
            ]
            self.fields["send_mode"].help_text = "Only the owner can switch a template to automatic."
        else:
            self.fields["send_mode"].help_text = (
                "“Send automatically” lets a reminder leave without anyone approving it."
            )
        self.fields["subject"].widget.attrs["data-merge-subject"] = "true"
        if self.instance.pk and self.instance.system:
            self.fields["channel"].disabled = True

    def clean(self):
        data = super().clean()
        if data.get("channel") == Channel.SMS:
            # Texts are plain: no markup survives.
            data["body"] = merge.html_to_text(data.get("body", ""))
        if data.get("channel") == Channel.SMS and data.get("subject"):
            data["subject"] = ""
        return data

    def clean_send_mode(self):
        mode = self.cleaned_data["send_mode"]
        if mode == MessageTemplate.SendMode.AUTO and not self.can_set_auto:
            if not (self.instance.pk and self.instance.send_mode == mode):
                raise ValidationError("Only the owner can switch a template to automatic.")
        return mode


class ScheduleForm(StyledFormMixin, forms.ModelForm):
    offsets_text = forms.CharField(
        label="Days",
        help_text="One number, or several separated by commas: 30, 7.",
    )
    send_mode = forms.ChoiceField(
        label="Its message", choices=MessageTemplate.SendMode.choices, required=False
    )

    class Meta:
        model = ReminderSchedule
        fields = [
            "template",
            "working_days",
            "repeat_every_days",
            "max_repeats",
            "step_name",
            "to_main_only",
            "active",
        ]
        labels = {
            "working_days": "Count the days as working days",
            "repeat_every_days": "Repeat every (days)",
            "max_repeats": "Repeat up to (more times)",
            "to_main_only": "Send to the main contact only",
            "active": "Switched on",
            "step_name": "Step that triggers it",
        }

    def __init__(self, *args, can_set_auto=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_set_auto = can_set_auto
        templates = MessageTemplate.objects.filter(active=True)
        if not sms_enabled():
            templates = templates.exclude(channel=Channel.SMS)
        self.fields["template"].queryset = templates.exclude(channel=Channel.LETTER)
        self.fields["offsets_text"].initial = ", ".join(str(o) for o in self.instance.offsets)
        if self.instance.trigger != ReminderSchedule.Trigger.STEP_TICKED:
            del self.fields["step_name"]
        if self.instance.template_id:
            self.fields["send_mode"].initial = self.instance.template.send_mode
        if not can_set_auto:
            self.fields["send_mode"].disabled = True
            self.fields["send_mode"].help_text = "Only the owner can change this."
        self.fields["send_mode"].choices = MessageTemplate.SendMode.choices

    def clean_offsets_text(self):
        raw = self.cleaned_data["offsets_text"]
        try:
            values = [int(part) for part in raw.replace(";", ",").split(",") if part.strip()]
        except ValueError as error:
            raise ValidationError("Use whole numbers, such as 30, 7.") from error
        if not values or any(v < 0 or v > 366 for v in values):
            raise ValidationError("Use numbers from 0 to 366.")
        return values

    def save(self, commit=True):
        schedule = super().save(commit=False)
        schedule.offsets = self.cleaned_data["offsets_text"]
        if not schedule.repeat_every_days:
            schedule.max_repeats = 0
        if commit:
            schedule.save()
        return schedule


class MessageEditForm(StyledFormMixin, forms.Form):
    to = forms.CharField(max_length=500, required=False, label="To")
    cc = forms.CharField(max_length=500, required=False, label="Cc")
    bcc = forms.CharField(max_length=500, required=False, label="Bcc")
    subject = forms.CharField(max_length=250, required=False)
    body = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, sms=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].widget.attrs["data-merge-subject"] = "true"
        if sms:
            del self.fields["cc"], self.fields["bcc"], self.fields["subject"]

    def clean_body(self):
        return clean_html(self.cleaned_data.get("body", ""))

    def _addresses(self, name):
        value = self.cleaned_data.get(name, "")
        try:
            services.check_addresses(value)
        except ValidationError as error:
            raise ValidationError(f"“{value}” has an address that does not look right.") from error
        return ", ".join(split_addresses(value))

    def clean_to(self):
        return self._addresses("to")

    def clean_cc(self):
        return self._addresses("cc")

    def clean_bcc(self):
        return self._addresses("bcc")


class ComposeForm(MessageEditForm):
    template = forms.ModelChoiceField(
        queryset=MessageTemplate.objects.none(), required=False, label="Start from a template"
    )
    contacts = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple, label="Send to"
    )
    attachments = forms.MultipleChoiceField(
        required=False, widget=forms.CheckboxSelectMultiple, label="Attach from Documents"
    )
    upload = forms.FileField(required=False, label="Or attach a new file")
    signature = forms.ChoiceField(
        choices=[("mine", "Mine"), ("none", "None")], initial="mine", label="Signature"
    )

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.fields["template"].queryset = MessageTemplate.objects.filter(
            active=True, channel=Channel.EMAIL
        )
        links = client.client_contacts.filter(resigned_on__isnull=True).select_related("contact")
        self.fields["contacts"].choices = [
            (link.contact.email, f"{link.contact.first_name} {link.contact.last_name} <{link.contact.email}>")
            for link in links
            if link.contact.email
        ]
        docs = client.documents.filter(deleted_at__isnull=True, sensitive=False)
        self.fields["attachments"].choices = [(str(d.pk), d.title) for d in docs]
        self.fields["to"].label = "Other addresses"
        self.fields["to"].widget.attrs["placeholder"] = "name@example.com, another@example.com"

    def clean(self):
        data = super().clean()
        picked = list(data.get("contacts") or [])
        extra = split_addresses(data.get("to", ""))
        merged = list(dict.fromkeys(picked + extra))
        data["to"] = ", ".join(merged)
        upload = data.get("upload")
        if upload:
            try:
                check_document_upload(upload)
            except ValidationError as error:
                self.add_error("upload", error)
        return data


class EmailLogForm(StyledFormMixin, forms.Form):
    on_date = forms.DateField(label="Date", widget=forms.DateInput(attrs={"type": "date"}))
    who = forms.CharField(max_length=150, label="With")
    summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="What it said")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["on_date"].widget.format = "%Y-%m-%d"


class BulkEmailForm(StyledFormMixin, forms.Form):
    template = forms.ModelChoiceField(
        queryset=MessageTemplate.objects.none(), label="Template", empty_label="Choose a template"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = MessageTemplate.objects.filter(
            active=True, channel=Channel.EMAIL
        )


class LetterForm(StyledFormMixin, forms.Form):
    template = forms.ModelChoiceField(
        queryset=MessageTemplate.objects.none(), label="Letter template"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = MessageTemplate.objects.filter(
            active=True, channel=Channel.LETTER
        )
