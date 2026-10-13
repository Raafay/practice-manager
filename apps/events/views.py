from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.core.pagination import paginate
from apps.core.permissions import CapabilityRequiredMixin, StaffRequiredMixin

from .forms import AuditFilterForm
from .models import ActivityEvent, Notification


class AuditLogView(CapabilityRequiredMixin, TemplateView):
    required_rights = ("audit.view",)
    template_name = "events/audit_log.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = AuditFilterForm(self.request.GET or None)
        events = form.filter(ActivityEvent.objects.select_related("actor", "target_type"))
        context["form"] = form
        context["page"] = paginate(self.request, events, per_page=50)
        return context


class NotificationListView(StaffRequiredMixin, TemplateView):
    template_name = "events/notifications.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = paginate(
            self.request, Notification.objects.for_user(self.request.user), per_page=30
        )
        return context


class OpenNotificationView(StaffRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, user=request.user)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at", "updated_at"])
        link = notification.link
        if not link or not url_has_allowed_host_and_scheme(
            link, allowed_hosts={request.get_host()}
        ):
            return redirect("events:notifications")
        return redirect(link)


class MarkAllReadView(StaffRequiredMixin, View):
    def post(self, request):
        Notification.objects.unread_for(request.user).update(
            read_at=timezone.now(), updated_at=timezone.now()
        )
        return redirect("events:notifications")
