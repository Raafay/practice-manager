"""Staff side of requests: the inbox, logging, converting, replying, closing."""

from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Value, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps import events
from apps.clients.models import Client
from apps.clients.views_base import done, render_form
from apps.comms import services as comms
from apps.core.dates import add_working_days
from apps.core.pagination import paginate
from apps.core.permissions import StaffRequiredMixin

from . import requests as services
from .forms_staff import (
    CloseForm,
    ConvertForm,
    LinkTaskForm,
    LogRequestForm,
    ReplyForm,
    SetClientForm,
)
from .models import Request, RequestFile

FILTERS = [
    ("open", "Open"),
    ("new", "New"),
    ("in_progress", "In progress"),
    ("answered", "Answered"),
    ("closed", "Closed"),
    ("spam", "Spam"),
    ("all", "All"),
]


def get_request(pk) -> Request:
    return get_object_or_404(
        Request.objects.select_related("client", "contact", "task", "logged_by"), pk=pk
    )


def inbox_queryset(state: str):
    queryset = Request.objects.select_related("client", "task")
    if state == "open":
        queryset = queryset.open()
    elif state in Request.State.values:
        queryset = queryset.filter(state=state)
    # New first, then urgent, then oldest first within new so nothing waits unseen.
    return queryset.annotate(
        rank=Case(
            When(state=Request.State.NEW, then=Value(0)),
            When(state=Request.State.IN_PROGRESS, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    ).order_by("rank", "-received_at")


class InboxView(StaffRequiredMixin, View):
    def get(self, request):
        state = request.GET.get("state", "open")
        if state not in dict(FILTERS):
            state = "open"
        page = paginate(request, inbox_queryset(state), per_page=50)
        counts = {
            "new": Request.objects.new().count(),
        }
        return render(
            request,
            "portal/inbox.html",
            {
                "page": page,
                "state": state,
                "filters": FILTERS,
                "counts": counts,
                "now": timezone.now(),
            },
        )


class RequestDetailView(StaffRequiredMixin, View):
    def get(self, request, pk):
        obj = get_request(pk)
        return render(
            request,
            "portal/inbox_detail.html",
            {"req": obj, "files": obj.files.all(), "proposal_note": bool(obj.proposal_id)},
        )


class LogRequestView(StaffRequiredMixin, View):
    """“Log a request”: paste a WhatsApp message, record a call. “Log and create task” does both."""

    def _render(self, request, form, status=200):
        return render_form(
            request,
            title="Log a request",
            form=form,
            action=request.path,
            target="drawer",
            submit="Log request",
            status=status,
            multipart=True,
            extra="portal/_log_extra.html",
            back=reverse("portal:inbox"),
        )

    def get(self, request):
        initial = {}
        if request.GET.get("client"):
            client = Client.objects.filter(pk=request.GET["client"]).first()
            if client is not None:
                initial["client_text"] = f"{client.name} ({client.reference})"
        return self._render(request, LogRequestForm(initial=initial))

    def post(self, request):
        form = LogRequestForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._render(request, form, 422)
        data = form.cleaned_data
        make_task = "log_task" in request.POST
        if make_task:
            if data["client_text"] is None:
                form.add_error("client_text", "Choose a client to create a task.")
            if data["category"] is None:
                form.add_error("category", "Choose a category for the task.")
            if data["owner"] is None:
                form.add_error("owner", "Choose who owns the task.")
            if form.errors:
                return self._render(request, form, 422)
        try:
            obj = services.create_request(
                channel=data["channel"],
                client=data["client_text"],
                sender_name=data["sender_name"],
                subject=data["subject"],
                body=data["body"],
                urgency=data["urgency"],
                uploads=request.FILES.getlist("files"),
                logged_by=request.user,
                notify=False,
            )
            if make_task:
                services.convert_to_task(
                    request.user,
                    obj,
                    category=data["category"],
                    owner=data["owner"],
                    target_date=data["target_date"],
                )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, form, 422)
        return done(request, reverse("portal:inbox_detail", args=[obj.pk]), "Request logged.")


class ConvertView(StaffRequiredMixin, View):
    def _form(self, obj, data=None):
        initial = {
            "title": obj.subject,
            "target_date": add_working_days(timezone.localdate(), 3),
            "owner": (obj.client.manager if obj.client else None) or None,
        }
        return ConvertForm(data, initial=initial, request_obj=obj)

    def _render(self, request, obj, form, status=200):
        return render_form(
            request,
            title="Make this a task",
            form=form,
            action=reverse("portal:inbox_convert", args=[obj.pk]),
            submit="Create task",
            status=status,
            intro="The task starts as kind “request”, with the text and any files carried over.",
            extra="tasks/_client_datalist.html",
            back=reverse("portal:inbox_detail", args=[obj.pk]),
        )

    def get(self, request, pk):
        obj = get_request(pk)
        return self._render(request, obj, self._form(obj))

    def post(self, request, pk):
        obj = get_request(pk)
        form = self._form(obj, request.POST)
        if not form.is_valid():
            return self._render(request, obj, form, 422)
        data = form.cleaned_data
        try:
            if obj.client is None:
                services.set_client(request.user, obj, data["client_text"])
            task = services.convert_to_task(
                request.user,
                obj,
                title=data["title"],
                category=data["category"],
                owner=data["owner"],
                target_date=data["target_date"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, obj, form, 422)
        return done(
            request, reverse("portal:inbox_detail", args=[obj.pk]), f"Task “{task.title}” created."
        )


class LinkTaskView(StaffRequiredMixin, View):
    def _render(self, request, obj, form, status=200):
        return render_form(
            request,
            title="Link to an existing task",
            form=form,
            action=reverse("portal:inbox_link", args=[obj.pk]),
            submit="Link",
            status=status,
            back=reverse("portal:inbox_detail", args=[obj.pk]),
        )

    def get(self, request, pk):
        obj = get_request(pk)
        return self._render(request, obj, LinkTaskForm(client=obj.client))

    def post(self, request, pk):
        obj = get_request(pk)
        form = LinkTaskForm(request.POST, client=obj.client)
        if not form.is_valid():
            return self._render(request, obj, form, 422)
        try:
            services.link_to_task(request.user, obj, form.cleaned_data["task"])
        except ValidationError as error:
            form.add_error(None, error)
            return self._render(request, obj, form, 422)
        return done(request, reverse("portal:inbox_detail", args=[obj.pk]), "Linked to the task.")


class ReplyView(StaffRequiredMixin, View):
    """Reply by email. The reply goes into the queue for approval like any other message."""

    def _render(self, request, obj, form, status=200):
        return render_form(
            request,
            title="Reply by email",
            form=form,
            action=reverse("portal:inbox_reply", args=[obj.pk]),
            submit="Queue the reply",
            status=status,
            intro="The reply waits in Queued messages until someone approves it.",
            back=reverse("portal:inbox_detail", args=[obj.pk]),
        )

    def get(self, request, pk):
        obj = get_request(pk)
        if obj.client is None:
            raise Http404
        initial = {"to": obj.sender_email, "subject": f"Re: {obj.subject}"}
        return self._render(request, obj, ReplyForm(initial=initial))

    def post(self, request, pk):
        obj = get_request(pk)
        if obj.client is None:
            raise Http404
        form = ReplyForm(request.POST)
        if not form.is_valid():
            return self._render(request, obj, form, 422)
        data = form.cleaned_data
        from django.utils.html import escape, linebreaks

        comms.create_message(
            obj.client,
            created_by=request.user,
            to=data["to"],
            subject=data["subject"],
            body_html=str(linebreaks(escape(data["body"]))),
            reason=f"Reply to request {obj.reference}",
            contact=obj.contact,
        )
        services.mark_answered(request.user, obj)
        return done(
            request, reverse("portal:inbox_detail", args=[obj.pk]), "Reply queued for approval."
        )


class CloseView(StaffRequiredMixin, View):
    def _render(self, request, obj, form, status=200):
        return render_form(
            request,
            title="Close this request",
            form=form,
            action=reverse("portal:inbox_close", args=[obj.pk]),
            submit="Close request",
            status=status,
            back=reverse("portal:inbox_detail", args=[obj.pk]),
        )

    def get(self, request, pk):
        return self._render(request, get_request(pk), CloseForm())

    def post(self, request, pk):
        obj = get_request(pk)
        form = CloseForm(request.POST)
        if not form.is_valid():
            return self._render(request, obj, form, 422)
        services.close(request.user, obj, form.cleaned_data["note"])
        return done(request, reverse("portal:inbox"), "Request closed.")


class SpamView(StaffRequiredMixin, View):
    def post(self, request, pk):
        services.mark_spam(request.user, get_request(pk))
        return done(request, reverse("portal:inbox"), "Marked as spam.")


class ReopenView(StaffRequiredMixin, View):
    def post(self, request, pk):
        obj = get_request(pk)
        services.reopen(request.user, obj)
        return done(request, reverse("portal:inbox_detail", args=[obj.pk]), "Reopened.")


class SetClientView(StaffRequiredMixin, View):
    def _render(self, request, obj, form, status=200):
        return render_form(
            request,
            title="Which client is this for?",
            form=form,
            action=reverse("portal:inbox_client", args=[obj.pk]),
            submit="Save",
            status=status,
            extra="tasks/_client_datalist.html",
            back=reverse("portal:inbox_detail", args=[obj.pk]),
        )

    def get(self, request, pk):
        return self._render(request, get_request(pk), SetClientForm())

    def post(self, request, pk):
        obj = get_request(pk)
        form = SetClientForm(request.POST)
        if not form.is_valid():
            return self._render(request, obj, form, 422)
        services.set_client(request.user, obj, form.cleaned_data["client_text"])
        return done(request, reverse("portal:inbox_detail", args=[obj.pk]), "Saved.")


class AttachmentView(StaffRequiredMixin, View):
    """Files on a request have no public address. Staff download them here."""

    def get(self, request, pk, public_id):
        entry = get_object_or_404(RequestFile, request_id=pk, public_id=public_id)
        events.record(
            request.user,
            "request.file_downloaded",
            f"{request.user} downloaded {entry.original_name} from request "
            f"{entry.request.reference}.",
            client=entry.request.client,
            target=entry.request,
        )
        response = FileResponse(
            entry.file.open("rb"),
            as_attachment=True,
            filename=entry.original_name,
            content_type=entry.content_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response
