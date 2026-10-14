"""Delivery reports from the email provider (spec 10 section 4).

The provider calls /email/events/ with the shared secret in EMAIL_WEBHOOK_SECRET
(HTTP basic auth, checked by django-anymail in constant time). Anymail turns each
report into a `tracking` signal; this module records what it means for the
message. A bounce or complaint shows on the Queued page and tells the person who
approved the message.
"""

from django.conf import settings
from django.dispatch import receiver
from django.http import Http404
from django.urls import reverse
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt

from apps import events

from .models import QueuedMessage

# Anymail's tracking view for each provider we support (the same keys as prod.py).
TRACKING_VIEWS = {
    "ses": "anymail.webhooks.amazon_ses.AmazonSESTrackingWebhookView",
    "postmark": "anymail.webhooks.postmark.PostmarkTrackingWebhookView",
    "brevo": "anymail.webhooks.brevo.BrevoTrackingWebhookView",
}

# Anymail event types, to what we keep. Everything else (queued, sent, opened,
# clicked, deferred) is not recorded: opens and clicks are not tracked.
DELIVERY_FOR_EVENT = {
    "delivered": QueuedMessage.Delivery.DELIVERED,
    "bounced": QueuedMessage.Delivery.BOUNCED,
    "rejected": QueuedMessage.Delivery.BOUNCED,
    "failed": QueuedMessage.Delivery.BOUNCED,
    "complained": QueuedMessage.Delivery.COMPLAINED,
}
PROBLEMS = (QueuedMessage.Delivery.BOUNCED, QueuedMessage.Delivery.COMPLAINED)


@csrf_exempt  # a server-to-server call; anymail checks the shared secret instead
def delivery_webhook(request):
    path = TRACKING_VIEWS.get(getattr(settings, "EMAIL_PROVIDER", ""))
    if path is None:
        raise Http404  # development and tests send nothing, so nothing reports back
    return import_string(path).as_view()(request)


def record(provider_message_id: str, delivery: str, *, reason: str = "") -> int:
    """Store a delivery report against its message. Returns how many were changed."""
    if delivery not in QueuedMessage.Delivery.values or not provider_message_id:
        return 0
    messages = list(
        QueuedMessage.objects.filter(provider_message_id=provider_message_id).select_related(
            "client", "approved_by", "created_by"
        )
    )
    for message in messages:
        if message.delivery_state == delivery:
            continue
        message.delivery_state = delivery
        message.save(update_fields=["delivery_state", "updated_at"])
        if delivery not in PROBLEMS:
            continue
        what = "bounced" if delivery == QueuedMessage.Delivery.BOUNCED else "was marked as spam"
        events.record(
            None,
            f"message.{delivery}",
            f"“{message.subject}” to {message.client.name} {what}.",
            actor_label="Email provider",
            client=message.client,
            target=message,
            reason=reason[:200],
        )
        person = message.approved_by or message.created_by
        if person is not None and person.is_active:
            events.notify(
                person,
                f"An email to {message.client.name} {what}. Check the address.",
                reverse("comms:message", args=[message.pk]),
                kind="message",
                key=f"delivery:{message.pk}:{delivery}",
            )
    return len(messages)


def _on_tracking(sender, event, esp_name, **kwargs):
    delivery = DELIVERY_FOR_EVENT.get(getattr(event, "event_type", ""))
    if delivery is None:
        return
    record(
        str(getattr(event, "message_id", "") or ""),
        delivery,
        reason=str(getattr(event, "reject_reason", "") or getattr(event, "description", "") or ""),
    )


def connect():
    from anymail.signals import tracking

    receiver(tracking, dispatch_uid="comms-delivery")(_on_tracking)
