from django import forms

from .forms import StyledFormMixin
from .models import PracticeSettings
from .theme import validate_readable_with_white
from .uploads import check_image_upload


class PracticeDetailsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PracticeSettings
        fields = [
            "practice_name",
            "address",
            "phone",
            "email",
            "logo",
            "accent_colour",
            "brand_colour",
            "email_footer",
            "vat_registered",
            "vat_rate",
            "retention_years",
            "aml_retention_years",
            "sending_address",
            "bcc_practice",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "accent_colour": forms.TextInput(attrs={"type": "color"}),
            "brand_colour": forms.TextInput(attrs={"type": "color"}),
            "email_footer": forms.Textarea(attrs={"rows": 3}),
            "logo": forms.FileInput(attrs={"accept": ".png,.jpg,.jpeg,.webp"}),
        }
        help_texts = {
            "logo": "PNG, JPEG or WebP, up to 2 MB.",
            "accent_colour": "Used for buttons and links.",
            "brand_colour": "The bar across the top of every staff page.",
        }

    def clean_accent_colour(self):
        value = self.cleaned_data["accent_colour"].lower()
        validate_readable_with_white(value)
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["brand_colour"].required = False

    def clean_brand_colour(self):
        value = (self.cleaned_data.get("brand_colour") or "").lower()
        if not value:
            return self.instance.brand_colour or "#0f172a"
        validate_readable_with_white(value)
        return value

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and logo is not self.instance.logo and hasattr(logo, "read"):
            self.logo_content_type = check_image_upload(logo, max_bytes=2 * 1024 * 1024)
        return logo

    def save(self, commit=True):
        instance = super().save(commit=False)
        if getattr(self, "logo_content_type", None):
            instance.logo_content_type = self.logo_content_type
        if commit:
            instance.save()
        return instance


class SecuritySettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PracticeSettings
        fields = ["mfa_trust_enabled", "session_idle_minutes", "session_max_hours"]
