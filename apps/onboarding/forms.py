from django import forms

from apps.core.forms import StyledFormMixin

from .models import ChecklistTemplateItem, OnboardingItem


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
