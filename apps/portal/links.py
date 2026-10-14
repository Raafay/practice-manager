"""Merge-field link builders for the portal (registered when the app loads).

portal_link, request_link, upload_link and confirm_link are filled in when a message is
made. upload_link and confirm_link also put a thing to do on the client's portal, once.
"""

from django.urls import reverse

from apps.comms import merge
from apps.core.siteurl import absolute

from . import requests as request_services
from . import services
from .models import PortalItem


def _task_for(ctx):
    if ctx.task is not None:
        return ctx.task
    if ctx.deadline is not None and ctx.deadline.pk:
        return ctx.deadline.tasks.filter(cancelled_at__isnull=True).order_by("-id").first()
    return None


def portal_link(client, ctx) -> str:
    return absolute(reverse("portal:home"))


def request_link(client, ctx) -> str:
    return absolute(request_services.link_path(client))


def _item_link(client, ctx, kind: str, title: str) -> str:
    task = _task_for(ctx)
    if task is not None:
        title = f"{title}: {task.title}"[:200]
    item = services.create_item(
        ctx.user if getattr(ctx.user, "pk", None) else None,
        client,
        kind,
        title,
        task=task,
        due_date=(ctx.deadline.due_date if ctx.deadline else None),
    )
    return absolute(reverse("portal:item", args=[item.public_id]))


def upload_link(client, ctx) -> str:
    return _item_link(client, ctx, PortalItem.Kind.UPLOAD_RECORDS, "Upload your records")


def confirm_link(client, ctx) -> str:
    return _item_link(client, ctx, PortalItem.Kind.CONFIRM_DETAILS, "Check your company details")


merge.LINK_BUILDERS.update(
    {
        "portal_link": portal_link,
        "request_link": request_link,
        "upload_link": upload_link,
        "confirm_link": confirm_link,
    }
)
