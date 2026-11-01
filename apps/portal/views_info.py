"""Information requests: ask a client for missing details by secure link or by post."""

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps import events
from apps.clients.views_base import done, get_client, render_form
from apps.core import ratelimit
from apps.core.forms import StyledFormMixin
from apps.core.permissions import StaffRequiredMixin
from apps.events.middleware import request_ip

from . import inforequest
from .access import no_index
from .models import InfoRequest


class NewInfoForm(StyledFormMixin, forms.Form):
    contact = forms.ChoiceField(label="Ask")
    channel = forms.ChoiceField(
        label="Send by",
        choices=InfoRequest.Channel.choices,
        widget=forms.RadioSelect,
        initial=InfoRequest.Channel.EMAIL,
    )

    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.people = {}
        choices = []
        for link in client.client_contacts.filter(resigned_on__isnull=True).select_related(
            "contact"
        ):
            gaps = inforequest.missing(client, link.contact)
            self.people[str(link.contact.pk)] = link.contact
            labels = ", ".join(inforequest.BY_KEY[k].label for k in gaps) or "nothing missing"
            choices.append((str(link.contact.pk), f"{link.contact.full_name} ({labels})"))
        self.fields["contact"].choices = choices
        self.fields["contact"].help_text = (
            "Only the details still empty on the record are asked for. Each person sees only "
            "their own."
        )

    def clean_contact(self):
        return self.people[self.cleaned_data["contact"]]


def get_info(pk, info_pk) -> InfoRequest:
    return get_object_or_404(
        InfoRequest.objects.select_related("client", "contact", "request"), pk=info_pk, client_id=pk
    )


class InfoNewView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title="Ask for missing details",
            form=form,
            action=reverse("portal:info_new", args=[client.pk]),
            submit="Create request",
            status=status,
            intro="By email, a secure link is queued for approval. It works for 28 days with "
            "reminders after 7 and 14. By post, print the form from the next page.",
        )

    def get(self, request, pk):
        client = get_client(pk)
        return self._render(request, client, NewInfoForm(client=client))

    def post(self, request, pk):
        client = get_client(pk)
        form = NewInfoForm(request.POST, client=client)
        if form.is_valid():
            try:
                info = inforequest.create(
                    request.user,
                    client,
                    form.cleaned_data["contact"],
                    channel=form.cleaned_data["channel"],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return done(
                    request,
                    reverse("portal:info_detail", args=[client.pk, info.pk]),
                    "Request created."
                    + (" The email is waiting in Queued." if info.channel == "email" else ""),
                )
        return self._render(request, client, form, 422)


class InfoDetailView(StaffRequiredMixin, View):
    def get(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        rows = [
            {
                "ask": ask,
                "answer": inforequest.shown_answer(ask, info.answers.get(ask.key, "")),
                "has_answer": ask.key in info.answers,
                "applied": ask.key in info.applied,
            }
            for ask in inforequest.asks_for(info)
        ]
        return render(
            request,
            "portal/info_detail.html",
            {
                "client": info.client,
                "info": info,
                "rows": rows,
                "still_missing": inforequest.still_missing(info),
                "files": info.request.files.all() if info.request else [],
            },
        )


class InfoApplyView(StaffRequiredMixin, View):
    def post(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        try:
            labels = inforequest.apply(request.user, info, request.POST.getlist("apply"))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Applied: {', '.join(labels) or 'nothing'}.")
        return redirect("portal:info_detail", pk, info_pk)


class InfoCancelView(StaffRequiredMixin, View):
    def post(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        try:
            inforequest.cancel(request.user, info)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("portal:info_detail", pk, info_pk)


class InfoPdfView(StaffRequiredMixin, View):
    def get(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        pdf = inforequest.postal_pdf(info)
        events.record(
            request.user,
            "info_request.printed",
            f"{request.user} printed the postal form for {info.reference}.",
            client=info.client,
            target=info,
        )
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{info.reference}.pdf"'
        return response


class InfoEnterView(StaffRequiredMixin, View):
    """Type in a paper form that came back by post."""

    def get(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        return render(
            request,
            "portal/info_enter.html",
            {"client": info.client, "info": info, "asks": inforequest.still_missing(info)},
        )

    def post(self, request, pk, info_pk):
        info = get_info(pk, info_pk)
        try:
            inforequest.record_postal_reply(request.user, info, request.POST)
        except ValidationError as error:
            return render(
                request,
                "portal/info_enter.html",
                {
                    "client": info.client,
                    "info": info,
                    "asks": inforequest.still_missing(info),
                    "errors": error.messages,
                },
                status=422,
            )
        return redirect("portal:info_detail", pk, info_pk)


# ---------------------------------------------------------------- the public link


def unavailable(request):
    return no_index(render(request, "portal/request_unavailable.html", status=404))


class InfoFormView(View):
    def _page(self, request, info, *, status=200, errors=(), values=None):
        return no_index(
            render(
                request,
                "portal/info_form.html",
                {
                    "info": info,
                    "client_name": info.client.name,
                    "asks": inforequest.still_missing(info),
                    "errors": errors,
                    "values": values or {},
                },
                status=status,
            )
        )

    def get(self, request, token):
        found = inforequest.link_for(token)
        if found is None:
            return unavailable(request)
        link, info = found
        if link.first_opened_at is None:
            from django.utils import timezone

            link.first_opened_at = timezone.now()
            link.save(update_fields=["first_opened_at", "updated_at"])
        return self._page(request, info)

    def post(self, request, token):
        found = inforequest.link_for(token)
        if found is None:
            return unavailable(request)
        link, info = found
        ip = request_ip(request) or ""
        if not ratelimit.hit(f"info-ip:{ip}", 10, 3600) or not ratelimit.hit(
            f"info-token:{link.pk}", 20, 86400
        ):
            return no_index(render(request, "portal/request_limited.html", status=429))
        try:
            inforequest.submit(
                link, info, request.POST, request.FILES.getlist("files"), ip=ip or None
            )
        except ValidationError as error:
            # Secret values are never echoed back into the page.
            values = {
                a.key: request.POST.get(a.key, "")
                for a in inforequest.still_missing(info)
                if not a.secret
            }
            return self._page(request, info, status=422, errors=error.messages, values=values)
        return no_index(
            render(request, "portal/info_thanks.html", {"client_name": info.client.name})
        )
