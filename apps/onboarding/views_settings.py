"""Settings: the onboarding checklist template."""

from django.views import View

from apps.clients.views_settings import DeleteMixin, EditMixin, SettingsListMixin

from .forms import ChecklistTemplateForm
from .models import ChecklistTemplateItem


class ChecklistListView(SettingsListMixin, View):
    model, noun = ChecklistTemplateItem, "checklist item"
    template_name = "onboarding/settings_checklist.html"


class ChecklistEditView(EditMixin, View):
    model, form_class, noun = ChecklistTemplateItem, ChecklistTemplateForm, "checklist item"
    list_url, edit_url = "onboarding:checklist", "onboarding:checklist_edit"


class ChecklistDeleteView(DeleteMixin, View):
    model, noun, list_url = ChecklistTemplateItem, "checklist item", "onboarding:checklist"

    def post(self, request, pk):
        from django.shortcuts import get_object_or_404

        item = get_object_or_404(ChecklistTemplateItem, pk=pk)
        if item.system_ticked:
            # Lines the system ticks cannot be deleted, only switched off.
            from django.contrib import messages
            from django.shortcuts import redirect

            messages.error(request, "That line is ticked by the system. Switch it off instead.")
            return redirect("onboarding:checklist")
        return super().post(request, pk)
