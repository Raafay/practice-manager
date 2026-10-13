"""The Queued page, the message editor, and writing to one client or many."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.accounts.models import User
from apps.clients import services as client_services
from apps.clients.models import Document
from apps.clients.views_base import done, get_client, render_form
from apps.core.pagination import paginate
from apps.core.permissions import StaffRequiredMixin

from . import letters, services
from .forms import (
    BulkEmailForm,
    ComposeForm,
    EmailLogForm,
    LetterForm,
    MessageEditForm,
)
from .models import Channel, MessageTemplate, QueuedMessage
from .sms import sms_enabled

STATE_RANK = Case(
    When(state="needs_approval", then=Value(0)),
    When(state="draft", then=Value(1)),
    When(state="failed", then=Value(2)),
    When(state="approved", then=Value(3)),
    When(state="sending", then=Value(4)),
    When(state="sent", then=Value(5)),
    default=Value(6),
    output_field=IntegerField(),
)


def message_queryset():
    return QueuedMessage.objects.select_related(
        "client", "template", "approved_by", "created_by", "client__manager"
    )


def problems_for(message: QueuedMessage) -> list[str]:
    return services.approval_problems(message) if message.is_editable else []


# ------------------------------------------------------------------ the queue


class QueueView(StaffRequiredMixin, View):
    def get(self, request):
        queryset = message_queryset()
        state = request.GET.get("state", "")
        template = request.GET.get("template", "")
        manager = request.GET.get("manager", "")
        q = request.GET.get("q", "").strip()
        if state:
            queryset = queryset.filter(state=state)
        else:
            # The default shows what needs doing, and recent history.
            from datetime import timedelta

            from django.utils import timezone

            recent = timezone.now() - timedelta(days=30)
            queryset = queryset.exclude(
                state__in=["sent", "cancelled"], created_at__lt=recent
            ).exclude(state="cancelled")
        if template.isdigit():
            queryset = queryset.filter(template_id=int(template))
        if manager.isdigit():
            queryset = queryset.filter(client__manager_id=int(manager))
        if q:
            queryset = queryset.filter(
                Q(client__name__icontains=q) | Q(subject__icontains=q) | Q(to__icontains=q)
            )
        queryset = queryset.annotate(rank=STATE_RANK).order_by("rank", "-created_at")
        page = paginate(request, queryset, per_page=50)
        for message in page.object_list:
            message.problems = problems_for(message)
            message.can_approve = services.can_approve(request.user, message)
        context = {
            "page": page,
            "state": state,
            "template_id": template,
            "manager_id": manager,
            "q": q,
            "states": QueuedMessage.State.choices,
            "templates": MessageTemplate.objects.order_by("name"),
            "managers": User.objects.filter(kind=User.Kind.STAFF, is_active=True),
            "paused": services.is_paused(),
            "can_pause": request.user.can("comms.pause"),
            "waiting": services.pending_count(),
        }
        return render(request, "comms/queue.html", context)


class MessageView(StaffRequiredMixin, View):
    """One message: read it, edit it, approve and send, save, cancel or retry."""

    def _context(self, request, message, form=None, status=200):
        form = form or MessageEditForm(
            initial={
                "to": message.to,
                "cc": message.cc,
                "bcc": message.bcc,
                "subject": message.subject,
                "body": message.body_html or message.body_text,
            },
            sms=message.channel == Channel.SMS,
        )
        person = services.sender_for(message)
        return {
            "message": message,
            "form": form,
            "problems": problems_for(message),
            "can_approve": services.can_approve(request.user, message),
            "sender": person,
            "paused": services.is_paused(),
            "from_address": services.sending_address(),
            "warning": services.warning_for(message.client),
            "attachments": message.attachments.all(),
        }

    def get(self, request, pk):
        message = get_object_or_404(message_queryset(), pk=pk)
        return render(request, "comms/message.html", self._context(request, message))

    def post(self, request, pk):
        message = get_object_or_404(message_queryset(), pk=pk)
        action = request.POST.get("action", "save")
        try:
            if action == "cancel":
                services.cancel(message, request.user)
                messages.success(request, "Message cancelled.")
                return redirect("comms:queue")
            if action == "retry":
                if not services.can_approve(request.user, message):
                    raise PermissionDenied
                services.retry(message, request.user)
                messages.success(request, "Queued to send again.")
                return redirect("comms:message", pk=message.pk)
            form = MessageEditForm(request.POST, sms=message.channel == Channel.SMS)
            if not form.is_valid():
                return render(
                    request,
                    "comms/message.html",
                    self._context(request, message, form, 422),
                    status=422,
                )
            data = form.cleaned_data
            if message.channel == Channel.SMS:
                message.body_text = data["body"] and services.merge.html_to_text(data["body"])
                message.to = data["to"]
                message.save()
            else:
                services.update_draft(
                    message,
                    request.user,
                    to=data["to"],
                    cc=data["cc"],
                    bcc=data["bcc"],
                    subject=data["subject"],
                    body_html=data["body"],
                )
            if action == "approve":
                message.refresh_from_db()
                services.approve(message, request.user)
                messages.success(
                    request,
                    "Approved. It will go out within a few minutes."
                    if not services.is_paused()
                    else "Approved. Sending is paused, so it will wait.",
                )
                return redirect("comms:queue")
            messages.success(request, "Saved.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        return redirect("comms:message", pk=message.pk)


class BulkApproveView(StaffRequiredMixin, View):
    def post(self, request):
        ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
        approved, skipped = 0, []
        for message in message_queryset().filter(pk__in=ids):
            try:
                services.approve(message, request.user)
                approved += 1
            except PermissionDenied:
                skipped.append(f"{message.client.name}: you may not approve this kind of message.")
            except ValidationError as error:
                skipped.append(f"{message.client.name}: {' '.join(error.messages)}")
        if approved:
            messages.success(request, f"Approved {approved} message{'s' if approved != 1 else ''}.")
        for line in skipped:
            messages.error(request, f"Not approved. {line}")
        if not ids:
            messages.error(request, "Tick the messages to approve first.")
        return redirect("comms:queue")


class PauseView(StaffRequiredMixin, View):
    def post(self, request):
        if not request.user.can("comms.pause"):
            raise PermissionDenied
        paused = request.POST.get("paused") == "1"
        services.set_paused(request.user, paused)
        messages.success(
            request,
            "All automatic sending is paused. Nothing will leave until you resume."
            if paused
            else "Sending has resumed.",
        )
        return redirect(request.POST.get("next") or "comms:queue")


# ------------------------------------------------------------------ one client


class ComposeView(StaffRequiredMixin, View):
    """Send email: a compose window on the client page."""

    def _form(self, request, client, data=None, files=None, template=None):
        initial = {}
        if template is not None and data is None:
            ctx = services.build_context(client, user=request.user)
            subject, html, _, _ = services.render_template(template, ctx)
            initial.update({"subject": subject, "body": html, "template": template.pk})
        main = services.main_contact(client)
        if main is not None and main.email and data is None:
            initial["contacts"] = [main.email]
        return ComposeForm(data, files, initial=initial, client=client)

    def _render(self, request, client, form, status=200):
        return render(
            request,
            "comms/compose.html",
            {
                "client": client,
                "form": form,
                "warning": services.warning_for(client),
                "sms": sms_enabled(),
            },
            status=status,
        )

    def get(self, request, pk):
        client = get_client(pk)
        template = None
        tid = request.GET.get("template", "")
        if tid.isdigit():
            template = MessageTemplate.objects.filter(
                pk=int(tid), active=True, channel=Channel.EMAIL
            ).first()
        return self._render(request, client, self._form(request, client, template=template))

    def post(self, request, pk):
        client = get_client(pk)
        form = self._form(request, client, request.POST, request.FILES)
        if request.POST.get("action") == "load_template":
            template = (
                form.fields["template"]
                .queryset.filter(pk=request.POST.get("template") or 0)
                .first()
            )
            return self._render(request, client, self._form(request, client, template=template))
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        if not data["to"]:
            form.add_error("contacts", "Choose at least one person to send to.")
            return self._render(request, client, form, 422)
        if not data["subject"].strip():
            form.add_error("subject", "Write a subject.")
            return self._render(request, client, form, 422)
        documents = list(client.documents.filter(pk__in=data["attachments"], sensitive=False))
        if data.get("upload"):
            documents.append(
                client_services.store_document(
                    request.user, client, data["upload"], category=Document.Category.CORRESPONDENCE
                )
            )
        message = services.create_message(
            client,
            created_by=request.user,
            template=data.get("template"),
            to=data["to"],
            cc=data["cc"],
            bcc=data["bcc"],
            subject=data["subject"],
            body_html=data["body"],
            state=QueuedMessage.State.NEEDS_APPROVAL,
            reason=f"Written by {request.user.name}.",
            contact=services.main_contact(client),
            attachments=documents,
            uses_signature=data["signature"] == "mine",
        )
        if request.POST.get("action") == "send":
            if not services.can_approve(request.user, message):
                raise PermissionDenied
            try:
                services.send_now(message, request.user)
            except ValidationError as error:
                message.state = QueuedMessage.State.DRAFT
                message.save(update_fields=["state", "updated_at"])
                form.add_error(None, " ".join(error.messages))
                return self._render(request, client, form, 422)
            message.refresh_from_db()
            if message.state == QueuedMessage.State.FAILED:
                messages.error(request, f"The email could not be sent: {message.error}")
            elif services.is_paused():
                messages.warning(request, "Approved, but sending is paused. It will wait.")
            else:
                messages.success(request, "Email sent.")
            return done(request, reverse("clients:timeline", args=[client.pk]))
        messages.success(request, "Saved to the queue. It needs approval before it goes out.")
        return done(request, reverse("comms:message", args=[message.pk]))


class LogEmailView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Log an email with {client.name}",
            form=form,
            action=reverse("comms:log_email", args=[client.pk]),
            submit="Log email",
            target="drawer",
            status=status,
            intro="Record an email that was sent or received outside the app.",
        )

    def get(self, request, pk):
        from django.utils import timezone

        client = get_client(pk)
        return self._render(
            request, client, EmailLogForm(initial={"on_date": timezone.localdate()})
        )

    def post(self, request, pk):
        client = get_client(pk)
        form = EmailLogForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        data = form.cleaned_data
        services.log_email(
            request.user,
            client,
            on_date=data["on_date"],
            who_with=data["who"],
            summary=data["summary"],
        )
        return done(request, reverse("clients:timeline", args=[client.pk]))


class LetterView(StaffRequiredMixin, View):
    def _render(self, request, client, form, status=200):
        return render_form(
            request,
            title=f"Create a letter for {client.name}",
            form=form,
            action=reverse("comms:letter", args=[client.pk]),
            submit="Create letter",
            target="drawer",
            status=status,
            intro="The letter is made as a PDF on the practice letterhead and saved to Documents.",
        )

    def get(self, request, pk):
        return self._render(request, get_client(pk), LetterForm())

    def post(self, request, pk):
        client = get_client(pk)
        form = LetterForm(request.POST)
        if not form.is_valid():
            return self._render(request, client, form, 422)
        try:
            letters.create_letter(request.user, client, form.cleaned_data["template"])
        except ValueError as error:
            form.add_error(None, str(error))
            return self._render(request, client, form, 422)
        messages.success(request, "Letter saved to Documents.")
        return done(request, reverse("clients:documents", args=[client.pk]))


class SmsView(StaffRequiredMixin, View):
    """Send SMS. Hidden, and a 404, unless a provider is configured."""

    def _render(self, request, client, status=200, error=""):
        return render(request, "comms/sms.html", {"client": client, "error": error}, status=status)

    def has_access(self, request) -> bool:
        if not sms_enabled():
            raise Http404
        return True

    def get(self, request, pk):
        return self._render(request, get_client(pk))

    def post(self, request, pk):
        client = get_client(pk)
        number = request.POST.get("to", "").strip()
        text = request.POST.get("text", "").strip()
        if not number or not text:
            return self._render(request, client, 422, "Give a mobile number and a message.")
        message = services.create_message(
            client,
            created_by=request.user,
            channel=Channel.SMS,
            to=number,
            body_text=text,
            reason=f"Written by {request.user.name}.",
            state=QueuedMessage.State.NEEDS_APPROVAL,
        )
        if request.POST.get("action") == "send" and services.can_approve(request.user, message):
            services.send_now(message, request.user)
        return done(request, reverse("clients:timeline", args=[client.pk]))


# ------------------------------------------------------------------ many clients


class BulkEmailView(StaffRequiredMixin, View):
    """Email these clients: pick a template, see who is skipped, then queue one per client."""

    def _clients(self, request):
        from apps.clients.forms import ClientFilterForm
        from apps.clients.views import _list_params, filtered_clients

        params, _ = _list_params(request)
        return filtered_clients(ClientFilterForm(params))

    def _plan(self, request, template):
        will, skipped = [], []
        for client in self._clients(request).select_related("manager", "partner"):
            reason = services.skip_reason(client, automatic=False)
            people = services.reminder_recipients(client)
            if not reason and not people:
                reason = "No email address."
            if reason:
                skipped.append((client, reason))
            else:
                will.append((client, people))
        return will, skipped

    def _render(self, request, form, template=None):
        will, skipped = self._plan(request, template) if template else ([], [])
        return render(
            request,
            "comms/bulk_email.html",
            {
                "form": form,
                "template": template,
                "will": will,
                "skipped": skipped,
                "query": request.GET.urlencode(),
            },
        )

    def get(self, request):
        form = BulkEmailForm(request.GET or None)
        template = form.cleaned_data["template"] if form.is_valid() else None
        return self._render(request, form, template)

    def post(self, request):
        form = BulkEmailForm(request.POST)
        if not form.is_valid():
            return self._render(request, form)
        template = form.cleaned_data["template"]
        will, _ = self._plan(request, template)
        made = 0
        for client, people in will:
            ctx = services.build_context(client, user=request.user, contact=people[0])
            subject, html, text, problems = services.render_template(template, ctx)
            if problems:
                continue
            services.create_message(
                client,
                created_by=request.user,
                template=template,
                to=", ".join(c.email for c in people),
                subject=subject,
                body_html=html,
                body_text=text,
                reason=f"Bulk email “{template.name}” by {request.user.name}.",
                contact=people[0],
            )
            made += 1
        messages.success(request, f"{made} message{'s' if made != 1 else ''} queued for approval.")
        return redirect("comms:queue")
