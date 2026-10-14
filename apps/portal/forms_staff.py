from django import forms
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy

from apps.accounts.models import User
from apps.core.forms import DateInput, StyledFormMixin
from apps.tasks.forms import resolve_client
from apps.tasks.models import Task, TaskCategory, TaskKind

from .models import Request


def client_widget():
    return forms.TextInput(
        attrs={
            "list": "client-options",
            "autocomplete": "off",
            "hx-get": reverse_lazy("tasks:client_options"),
            "hx-trigger": "input changed delay:250ms",
            "hx-target": "#client-options",
            "hx-swap": "innerHTML",
        }
    )


LOG_CHANNELS = [
    (Request.Channel.WHATSAPP, "WhatsApp"),
    (Request.Channel.PHONE, "Phone"),
    (Request.Channel.EMAIL, "Email"),
    (Request.Channel.IN_PERSON, "In person"),
]


def category_choices():
    return TaskCategory.objects.filter(kind=TaskKind.REQUEST).order_by("name") or (
        TaskCategory.objects.all().order_by("name")
    )


class LogRequestForm(StyledFormMixin, forms.Form):
    channel = forms.ChoiceField(choices=LOG_CHANNELS, initial=Request.Channel.WHATSAPP)
    client_text = forms.CharField(
        label="Client",
        required=False,
        widget=client_widget(),
        help_text="Leave empty for a general request.",
    )
    sender_name = forms.CharField(label="Who asked", max_length=150, required=False)
    subject = forms.CharField(max_length=200, required=False)
    body = forms.CharField(
        label="What they asked (paste it in)",
        max_length=10000,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    urgency = forms.ChoiceField(choices=Request.Urgency.choices, initial="normal")
    # Used by "Log and create task"
    category = forms.ModelChoiceField(
        queryset=TaskCategory.objects.none(), required=False, label="Task category"
    )
    owner = forms.ModelChoiceField(
        queryset=User.objects.staff().filter(is_active=True), required=False, label="Task owner"
    )
    target_date = forms.DateField(required=False, widget=DateInput(), label="Task target date")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = category_choices()

    def clean_client_text(self):
        return resolve_client(self.cleaned_data.get("client_text", ""))


class ConvertForm(StyledFormMixin, forms.Form):
    title = forms.CharField(max_length=250)
    client_text = forms.CharField(
        label="Client",
        required=False,
        widget=client_widget(),
    )
    category = forms.ModelChoiceField(queryset=TaskCategory.objects.none())
    owner = forms.ModelChoiceField(queryset=User.objects.staff().filter(is_active=True))
    target_date = forms.DateField(widget=DateInput())

    def __init__(self, *args, request_obj=None, **kwargs):
        self.request_obj = request_obj
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = category_choices()
        if request_obj is not None and request_obj.client_id:
            del self.fields["client_text"]

    def clean_client_text(self):
        client = resolve_client(self.cleaned_data.get("client_text", ""))
        if client is None:
            raise ValidationError("Choose a client for this task.")
        return client


class CloseForm(StyledFormMixin, forms.Form):
    note = forms.CharField(
        label="Closing note", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )


class ReplyForm(StyledFormMixin, forms.Form):
    to = forms.EmailField(label="To")
    subject = forms.CharField(max_length=250)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}))


class LinkTaskForm(StyledFormMixin, forms.Form):
    task = forms.ModelChoiceField(queryset=Task.objects.none(), label="Task")

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Task.objects.open()
        if client is not None:
            queryset = queryset.filter(client=client)
        self.fields["task"].queryset = queryset.select_related("client").order_by("-created_at")[
            :100
        ]
        self.fields["task"].label_from_instance = lambda t: (
            f"{t.title} ({t.client.name if t.client else 'general'})"
        )


class SetClientForm(StyledFormMixin, forms.Form):
    client_text = forms.CharField(
        label="Client",
        required=False,
        widget=client_widget(),
        help_text="Leave empty to keep it as a general request.",
    )

    def clean_client_text(self):
        return resolve_client(self.cleaned_data.get("client_text", ""))
