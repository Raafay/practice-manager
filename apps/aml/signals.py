"""Keep the onboarding checklist and AML reviews in step with what happens elsewhere."""

from django.dispatch import receiver

from apps.clients.models import Client
from apps.clients.services import status_changed
from apps.companieshouse.services import client_synced
from apps.onboarding import services as onboarding
from apps.services.services import service_added

from . import services
from .models import AmlSettings


@receiver(services.assessment_approved, dispatch_uid="aml_assessment_approved")
def on_approved(sender, assessment, actor=None, **kwargs):
    onboarding.tick(
        assessment.client,
        "risk_assessment_approved",
        actor=actor,
        note=f"Approved at {assessment.level} risk.",
        auto=True,
    )


@receiver(services.identity_changed, dispatch_uid="aml_identity_changed")
def on_identity_changed(sender, client, **kwargs):
    onboarding.sync_system_item(client, "identity_verified", services.all_verified(client))


@receiver(client_synced, dispatch_uid="aml_client_synced")
def on_client_synced(sender, client, result=None, **kwargs):
    if result is not None and getattr(result, "people_changed", False) and not result.first:
        services.prompt_review(client, "A director or owner changed at Companies House.")


@receiver(service_added, dispatch_uid="aml_service_added")
def on_service_added(sender, client, client_service, actor=None, **kwargs):
    if AmlSettings.load().higher_risk_services.filter(pk=client_service.service_id).exists():
        services.prompt_review(client, f"Higher-risk service added: {client_service.service.name}.")


@receiver(status_changed, dispatch_uid="aml_status_changed")
def on_status_changed(sender, client, old, new, actor=None, **kwargs):
    if new == Client.Status.ACTIVE and old in (Client.Status.FORMER, Client.Status.LOST):
        services.prompt_review(client, "The client was reactivated.")
