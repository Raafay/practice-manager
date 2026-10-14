"""The Overview page: my work, deadlines for my clients, and what is waiting on me."""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.clients.models import Client
from apps.events.models import Notification
from apps.services.models import Deadline

from .models import Task

DEADLINE_DAYS = 14
LIMIT = 10


def deadlines_for_my_clients(user, today: date | None = None) -> list[Deadline]:
    """Open deadlines due within 14 days, or overdue, for clients I manage or partner."""
    today = today or timezone.localdate()
    mine = Client.objects.not_archived().filter(Q(manager=user) | Q(partner=user))
    return list(
        Deadline.objects.open()
        .filter(client__in=mine, due_date__lte=today + timedelta(days=DEADLINE_DAYS))
        .exclude(client__status__in=(Client.Status.FORMER, Client.Status.LOST))
        .select_related("client")
        .order_by("due_date", "client__name")[: LIMIT * 3]
    )


def waiting_on_me(user) -> dict:
    """Tasks I review that someone else owns, and unread mentions."""
    reviews = list(
        Task.objects.open()
        .filter(reviewer=user)
        .exclude(owner=user)
        .select_related("client", "owner", "status")
        .order_by("target_date", "due_date", "id")[:LIMIT]
    )
    mentions = list(Notification.objects.unread_for(user).filter(kind="mention")[:LIMIT])
    return {"reviews": reviews, "mentions": mentions, "total": len(reviews) + len(mentions)}
