from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.core.fields import mask
from apps.core.permissions import StaffRequiredMixin

from . import services
from .forms import (
    ClientContactForm,
    ContactForm,
    LinkForm,
    NewContactForm,
)
from .models import Client, ClientContact, ClientLink, Contact
from .panels import pretty_label
from .views_base import done, get_client, render_form

CONTACT_SENSITIVE = ("ni_number", "personal_utr", "ch_personal_code")


class ContactAddView(StaffRequiredMixin, View):
    """Search for an existing person first, then add a new one if needed."""

    def _context(self, client, *, query="", form=None, matches=None, confirm=False):
        if matches is None:
            matches = services.search_contacts(query)[:10] if len(query) >= 2 else []
        linked = set(client.client_contacts.values_list("contact_id", flat=True))
        return {
            "client": client,
            "q": query,
            "matches": [m for m in matches if m.pk not in linked],
            "form": form or NewContactForm(),
            "confirm": confirm,
        }

    def get(self, request, pk):
        client = get_client(pk)
        query = request.GET.get("q", "").strip()
        context = self._context(client, query=query)
        template = (
            "clients/_contact_matches.html"
            if request.GET.get("matches")
            else "clients/_contact_add.html"
        )
        return render(request, template, context)

    def post(self, request, pk):
        client = get_client(pk)
        form = NewContactForm(request.POST)
        if not form.is_valid():
            return render(
                request, "clients/_contact_add.html", self._context(client, form=form), status=422
            )
        data = form.cleaned_data
        matches = services.find_matching_contacts(
            email=data["email"], first_name=data["first_name"], last_name=data["last_name"]
        ).exclude(client_links__client=client)
        if matches.exists() and not request.POST.get("confirm_new"):
            return render(
                request,
                "clients/_contact_add.html",
                self._context(client, form=form, matches=list(matches), confirm=True),
                status=422,
            )
        contact = services.create_contact(request.user, **data)
        services.add_contact(request.user, client, contact)
        return done(
            request,
            reverse("clients:contacts", args=[client.pk]),
            f"{contact.full_name} was added.",
        )


class ContactLinkView(StaffRequiredMixin, View):
    """Link a person who is already on file."""

    def post(self, request, pk, contact_pk):
        client = get_client(pk)
        contact = get_object_or_404(Contact, pk=contact_pk)
        try:
            services.add_contact(request.user, client, contact)
        except ValidationError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, f"{contact.full_name} was linked to {client.name}.")
        return done(request, reverse("clients:contacts", args=[client.pk]))


class ClientContactEditView(StaffRequiredMixin, View):
    def _link(self, pk, link_pk) -> ClientContact:
        return get_object_or_404(
            ClientContact.objects.select_related("client", "contact"), pk=link_pk, client_id=pk
        )

    def _render(self, request, link, form, status=200):
        return render_form(
            request,
            title=f"{link.contact.full_name} at {link.client.name}",
            form=form,
            action=reverse("clients:contact_edit", args=[link.client_id, link.pk]),
            target="drawer",
            status=status,
        )

    def get(self, request, pk, link_pk):
        link = self._link(pk, link_pk)
        return self._render(request, link, ClientContactForm(instance=link))

    def post(self, request, pk, link_pk):
        link = self._link(pk, link_pk)
        form = ClientContactForm(request.POST, instance=link)
        if not form.is_valid():
            return self._render(request, link, form, 422)
        services.save_client_contact(request.user, link, form)
        return done(request, reverse("clients:contacts", args=[link.client_id]), "Saved.")


class ClientContactUnlinkView(StaffRequiredMixin, View):
    def post(self, request, pk, link_pk):
        link = get_object_or_404(
            ClientContact.objects.select_related("client", "contact"), pk=link_pk, client_id=pk
        )
        name, client_id = link.contact.full_name, link.client_id
        services.unlink_contact(request.user, link)
        return done(
            request,
            reverse("clients:contacts", args=[client_id]),
            f"{name} was unlinked. The person is still on file.",
        )


# ------------------------------------------------------------ the person's own page


class ContactDetailView(StaffRequiredMixin, View):
    def get(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        sensitive = [
            {
                "name": name,
                "label": pretty_label(contact._meta.get_field(name).verbose_name),
                "masked": mask(getattr(contact, name)) if getattr(contact, name) else "",
            }
            for name in CONTACT_SENSITIVE
        ]
        links = contact.client_links.select_related("client").order_by("client__name")
        return render(
            request,
            "clients/contact_detail.html",
            {
                "contact": contact,
                "sensitive": sensitive,
                "links": links,
                "back_client": request.GET.get("client", ""),
            },
        )


class ContactEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        return render(
            request,
            "clients/contact_form.html",
            {"contact": contact, "form": ContactForm(instance=contact)},
        )

    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        form = ContactForm(request.POST, instance=contact)
        if not form.is_valid():
            return render(
                request, "clients/contact_form.html", {"contact": contact, "form": form}, status=422
            )
        services.update_contact(request.user, contact, form)
        messages.success(request, "Saved.")
        return redirect("clients:contact_detail", pk=contact.pk)


class ContactRevealView(StaffRequiredMixin, View):
    def post(self, request, pk, field):
        contact = get_object_or_404(Contact, pk=pk)
        client = None
        client_id = request.POST.get("client")
        if client_id and client_id.isdigit():
            # Only a client this person is linked to: the reveal is logged on its timeline.
            client = Client.objects.filter(pk=client_id, client_contacts__contact=contact).first()
        value = services.reveal_value(request.user, contact, field, client=client)
        response = render(request, "clients/_revealed.html", {"value": value, "name": field})
        response["Cache-Control"] = "no-store"
        return response


class PersonalTaxClientView(StaffRequiredMixin, View):
    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        from_client = None
        client_id = request.POST.get("client")
        if client_id and client_id.isdigit():
            from_client = Client.objects.filter(pk=client_id).first()
        try:
            client = services.create_personal_tax_client(request.user, contact, from_client)
        except ValidationError as error:
            messages.error(request, error.message)
            if from_client:
                return redirect("clients:detail", pk=from_client.pk)
            return redirect("clients:contact_detail", pk=contact.pk)
        messages.success(
            request, f"Personal tax client {client.name} ({client.reference}) was created."
        )
        return redirect("clients:detail", pk=client.pk)


# ------------------------------------------------------------ links between clients


class LinkAddView(StaffRequiredMixin, View):
    def _context(self, client, form, query=""):
        matches = []
        if len(query) >= 2:
            matches = list(services.search_clients(query).exclude(pk=client.pk)[:10])
        return {"client": client, "form": form, "q": query, "matches": matches}

    def get(self, request, pk):
        client = get_client(pk)
        query = request.GET.get("q", "").strip()
        if request.GET.get("matches"):
            return render(
                request,
                "clients/_link_matches.html",
                self._context(client, LinkForm(client=client), query),
            )
        return render(
            request, "clients/_link_add.html", self._context(client, LinkForm(client=client), query)
        )

    def post(self, request, pk):
        client = get_client(pk)
        form = LinkForm(request.POST, client=client)
        if not form.is_valid():
            return render(
                request, "clients/_link_add.html", self._context(client, form), status=422
            )
        data = form.cleaned_data
        try:
            services.add_link(
                request.user, client, data["other"], data["relationship"], data["note"]
            )
        except ValidationError as error:
            form.add_error(None, error)
            return render(
                request, "clients/_link_add.html", self._context(client, form), status=422
            )
        return done(request, reverse("clients:links", args=[client.pk]), "Link added.")


class LinkRemoveView(StaffRequiredMixin, View):
    def post(self, request, pk, link_pk):
        client = get_client(pk)
        link = get_object_or_404(ClientLink, pk=link_pk)
        if client.pk not in (link.client_a_id, link.client_b_id):
            raise Http404
        services.remove_link(request.user, link)
        return done(request, reverse("clients:links", args=[client.pk]), "Link removed.")
