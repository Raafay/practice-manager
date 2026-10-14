"""The client HMRC tab: one row per tax."""

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from apps.clients.views import ClientTabView
from apps.clients.views_base import done, get_client, render_form
from apps.core.fields import mask
from apps.core.permissions import StaffRequiredMixin

from . import hmrc
from .forms import AuthorisationAddForm, AuthorisationForm
from .models import AgentAuthorisation


class HmrcTabView(ClientTabView):
    tab = "hmrc"
    tab_template = "onboarding/tabs/_hmrc.html"

    def context_hmrc(self, request, client):
        rows = list(client.agent_authorisations.select_related("contact"))
        for row in rows:
            row.masked_code = mask(row.code) if row.code else ""
        return {
            "auths": rows,
            "missing": hmrc.missing(client),
            "needed": hmrc.needed(client),
        }


class AuthorisationAddView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title="Add an HMRC authorisation",
            form=form,
            action=reverse("onboarding:hmrc_add", args=[client.pk]),
            submit="Add",
            status=status,
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, AuthorisationAddForm(client=client))

    def post(self, request, pk):
        client = get_client(pk)
        form = AuthorisationAddForm(request.POST, client=client)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        try:
            hmrc.add(
                request.user,
                client,
                tax=data["tax"],
                method=data["method"],
                contact=data["contact"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, client, form, 422)
        return done(request, reverse("onboarding:hmrc", args=[pk]))


class AuthorisationEditView(StaffRequiredMixin, View):
    def _auth(self, pk, auth_pk):
        return get_object_or_404(AgentAuthorisation, pk=auth_pk, client_id=pk)

    def _render(self, request, auth, form, status=200):
        return render_form(
            request,
            title=f"{auth.get_tax_display()} authorisation",
            form=form,
            action=reverse("onboarding:hmrc_edit", args=[auth.client_id, auth.pk]),
            target="drawer",
            status=status,
        )

    def get(self, request, pk, auth_pk):
        auth = self._auth(pk, auth_pk)
        return self._render(request, auth, AuthorisationForm.for_instance(auth))

    def post(self, request, pk, auth_pk):
        auth = self._auth(pk, auth_pk)
        form = AuthorisationForm(request.POST, client=auth.client)
        if not form.is_valid():
            return self._render(request, auth, form, 422)
        hmrc.update(request.user, auth, form.cleaned_data)
        return done(request, reverse("onboarding:hmrc", args=[pk]))


class AuthorisationRevealView(StaffRequiredMixin, View):
    """Show the saved code. A POST, always logged."""

    def post(self, request, pk, auth_pk):
        auth = get_object_or_404(AgentAuthorisation, pk=auth_pk, client_id=pk)
        value = hmrc.reveal_code(request.user, auth)
        response = render(
            request,
            "clients/_revealed.html",
            {"value": value, "name": f"hmrc-{auth.pk}"},
        )
        response["Cache-Control"] = "no-store"
        return response
