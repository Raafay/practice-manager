from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from apps import events
from apps.core.permissions import CapabilityRequiredMixin

from .forms import CustomFieldForm, TagForm
from .models import CustomFieldDefinition, Tag
from .views_base import done, render_form


class SettingsListMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)
    model = None
    form_class = None
    list_url = ""
    noun = ""
    template_name = ""

    def objects(self):
        return self.model.objects.all()

    def get(self, request):
        return render(
            request,
            self.template_name,
            {"items": self.objects(), "noun": self.noun},
        )


class EditMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)
    model = None
    form_class = None
    list_url = ""
    noun = ""
    edit_url = ""

    def instance(self, pk):
        return get_object_or_404(self.model, pk=pk) if pk else self.model()

    def _render(self, request, form, instance, status=200):
        action = (
            reverse(self.edit_url, args=[instance.pk])
            if instance.pk
            else reverse(self.edit_url.replace("edit", "add"))
        )
        return render_form(
            request,
            title=f"Edit {self.noun}" if instance.pk else f"New {self.noun}",
            form=form,
            action=action,
            target="drawer",
            status=status,
        )

    def get(self, request, pk=None):
        instance = self.instance(pk)
        return self._render(request, self.form_class(instance=instance), instance)

    def post(self, request, pk=None):
        instance = self.instance(pk)
        form = self.form_class(request.POST, instance=instance)
        if not form.is_valid():
            return self._render(request, form, instance, 422)
        creating = instance.pk is None
        saved = form.save()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} {'added' if creating else 'changed'} the {self.noun} “{saved}”.",
            setting=self.noun,
        )
        return done(request, reverse(self.list_url), f"{self.noun.capitalize()} saved.")


class DeleteMixin(CapabilityRequiredMixin):
    required_rights = ("settings.manage",)
    model = None
    list_url = ""
    noun = ""

    def post(self, request, pk):
        instance = get_object_or_404(self.model, pk=pk)
        name = str(instance)
        instance.delete()
        events.record(
            request.user,
            "setting.changed",
            f"{request.user} deleted the {self.noun} “{name}”.",
            setting=self.noun,
        )
        return done(request, reverse(self.list_url), f"{self.noun.capitalize()} deleted.")


class TagListView(SettingsListMixin, View):
    model, noun, template_name = Tag, "tag", "clients/settings_tags.html"

    def objects(self):
        from django.db.models import Count

        return Tag.objects.annotate(uses=Count("clients"))


class TagEditView(EditMixin, View):
    model, form_class, noun = Tag, TagForm, "tag"
    list_url, edit_url = "clients:tags", "clients:tag_edit"


class TagDeleteView(DeleteMixin, View):
    model, noun, list_url = Tag, "tag", "clients:tags"


class CustomFieldListView(SettingsListMixin, View):
    model, noun, template_name = (
        CustomFieldDefinition,
        "custom field",
        "clients/settings_custom_fields.html",
    )


class CustomFieldEditView(EditMixin, View):
    model, form_class, noun = CustomFieldDefinition, CustomFieldForm, "custom field"
    list_url, edit_url = "clients:custom_fields", "clients:custom_field_edit"


class CustomFieldDeleteView(DeleteMixin, View):
    model, noun, list_url = CustomFieldDefinition, "custom field", "clients:custom_fields"
