"""Keep the portal in step with letters, proposals and tasks.

A letter or proposal that is sent puts a thing to do on the portal for the person it was
sent to, if they have portal access. When it is signed, decided or withdrawn the item is
closed. A request closes by itself when its task is done.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.onboarding.models import EngagementLetter
from apps.pipeline.models import Proposal
from apps.tasks.models import Task

from . import requests as request_services
from . import services
from .models import PortalItem


def _has_access(contact, client) -> bool:
    return bool(
        contact is not None
        and contact.portal_user_id
        and contact.client_links.filter(client=client, portal_access=True).exists()
    )


@receiver(post_save, sender=EngagementLetter, dispatch_uid="portal_letter_item")
def on_letter_saved(sender, instance, **kwargs):
    kind = PortalItem.Kind.SIGN_LETTER
    if instance.state in ("sent", "viewed"):
        if _has_access(instance.signer, instance.client):
            services.create_item(
                None,
                instance.client,
                kind,
                "Read and sign your engagement letter",
                contact=instance.signer,
                object_id=instance.pk,
            )
    elif instance.state == "signed":
        services.sync_item_for(kind, instance.pk, instance.client, contact=instance.signer)
    elif instance.state in ("cancelled", "replaced"):
        for item in PortalItem.objects.filter(
            client=instance.client, kind=kind, object_id=instance.pk, state="open"
        ):
            services.cancel_item(None, item)


@receiver(post_save, sender=Proposal, dispatch_uid="portal_proposal_item")
def on_proposal_saved(sender, instance, **kwargs):
    kind = PortalItem.Kind.ACCEPT_PROPOSAL
    if instance.state in ("sent", "viewed"):
        if _has_access(instance.contact, instance.client):
            services.create_item(
                None,
                instance.client,
                kind,
                "Read your proposal",
                contact=instance.contact,
                object_id=instance.pk,
                due_date=instance.valid_until,
            )
    elif instance.state in ("accepted", "declined", "expired"):
        services.sync_item_for(kind, instance.pk, instance.client, contact=instance.contact)
    elif instance.state == "withdrawn":
        for item in PortalItem.objects.filter(
            client=instance.client, kind=kind, object_id=instance.pk, state="open"
        ):
            services.cancel_item(None, item)


@receiver(post_save, sender=Task, dispatch_uid="portal_task_done")
def on_task_saved(sender, instance, **kwargs):
    if instance.status_id and instance.status.is_done:
        request_services.close_for_done_task(instance)
