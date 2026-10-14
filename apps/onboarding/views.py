"""The Onboarding tab and the go-live gate."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View

from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from . import services
from .forms import ItemForm, MakeLiveForm
from .models import OnboardingItem


class OnboardingTabView(ClientTabView):
    tab = "onboarding"
    tab_template = "onboarding/tabs/_onboarding.html"

    def context_onboarding(self, request, client):
        if client.status == client.Status.ONBOARDING:
            services.ensure_checklist(client)
        problems = services.gate_problems(client)
        return {
            "items": client.onboarding_items.all(),
            "progress": services.progress(client),
            "problems": problems,
            "can_make_live": client.status == client.Status.ONBOARDING
            and request.user.can("clients.status"),
            "can_override": request.user.can("onboarding.override"),
        }


class ItemEditView(StaffRequiredMixin, View):
    def _item(self, pk, item_pk):
        return get_object_or_404(OnboardingItem, pk=item_pk, client_id=pk)

    def _render(self, request, item, form, status=200):
        return render_form(
            request,
            title=item.name,
            form=form,
            action=reverse("onboarding:item", args=[item.client_id, item.pk]),
            status=status,
            intro="Items marked as set by the system tick themselves when the work is done. "
            "You can also set them by hand.",
        )

    def get(self, request, pk, item_pk):
        item = self._item(pk, item_pk)
        return self._render(
            request, item, ItemForm(initial={"state": item.state, "note": item.note})
        )

    def post(self, request, pk, item_pk):
        item = self._item(pk, item_pk)
        form = ItemForm(request.POST)
        if not form.is_valid():
            return self._render(request, item, form, 422)
        services.set_item(request.user, item, form.cleaned_data["state"], form.cleaned_data["note"])
        return done(request, reverse("onboarding:tab", args=[pk]))


class MakeLiveView(CapabilityRequiredMixin, View):
    required_rights = ("clients.status",)

    def _render(self, request, client, form, status=200):
        problems = services.gate_problems(client)
        intro = (
            "Everything needed is done. Making the client live turns the proposed services on "
            "and creates their deadlines."
            if not problems
            else "Still open: " + "; ".join(problems) + "."
        )
        if problems and not request.user.can("onboarding.override"):
            intro += " Only someone with the override right can go live with these open."
        return render_form(
            request,
            title=f"Make {client.name} live",
            form=form,
            action=reverse("onboarding:make_live", args=[client.pk]),
            submit="Make live",
            status=status,
            intro=intro,
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, MakeLiveForm())

    def post(self, request, pk):
        client = get_client(pk)
        form = MakeLiveForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        try:
            services.make_live(request.user, client, override_reason=form.cleaned_data["reason"])
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, client, form, 422)
        except PermissionDenied:
            raise
        return done(
            request, reverse("clients:detail", args=[client.pk]), f"{client.name} is now live."
        )
