"""The AML register: every client with its level, state, last assessment and review date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django import forms
from django.utils import timezone

from apps.clients.models import Client
from apps.core.forms import StyledFormMixin

from . import services
from .models import RiskAssessment

LIVE = (Client.Status.ACTIVE, Client.Status.PAUSED, Client.Status.ONBOARDING)


class RegisterFilterForm(StyledFormMixin, forms.Form):
    q = forms.CharField(required=False, label="Client")
    level = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any level"),
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("none", "No level yet"),
        ],
    )
    state = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Any state"),
            ("not_started", "Not started"),
            ("in_progress", "In progress"),
            ("awaiting_approval", "Awaiting approval"),
            ("approved", "Approved"),
            ("review_due", "Review due"),
            ("review_overdue", "Review overdue"),
            ("needs_review", "Needs review (imported)"),
        ],
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Active, onboarding and paused"),
            ("former", "Former clients"),
            ("all", "All clients"),
        ],
    )


@dataclass
class Row:
    client: Client
    level: str
    level_label: str
    state_key: str
    state_label: str
    state_tone: str
    last_assessed: date | None
    next_review: date | None
    verified: int
    total: int

    @property
    def level_tone(self) -> str:
        return {"low": "green", "medium": "amber", "high": "red"}.get(self.level, "neutral")


def build_rows(form: RegisterFilterForm) -> list[Row]:
    data = form.cleaned_data if form.is_valid() else {}
    clients = Client.objects.not_archived().prefetch_related(
        "risk_assessments", "identity_checks", "onboarding_items"
    )
    status = data.get("status") or ""
    if status == "former":
        clients = clients.filter(status=Client.Status.FORMER)
    elif status != "all":
        clients = clients.filter(status__in=LIVE)
    else:
        clients = clients.exclude(status__in=(Client.Status.LOST, Client.Status.PROSPECT))
    if data.get("q"):
        clients = clients.filter(name__icontains=data["q"])
    rows = []
    for client in clients.order_by("name"):
        assessments = list(client.risk_assessments.all())
        approved = next((a for a in assessments if a.state == RiskAssessment.State.APPROVED), None)
        key, label, tone = services.state_of(client)
        checks = [c for c in client.identity_checks.all() if not c.excluded]
        assessed = [a.assessed_at for a in assessments if a.assessed_at]
        rows.append(
            Row(
                client=client,
                level=approved.level if approved else "",
                level_label=approved.get_level_display() if approved else "",
                state_key=key,
                state_label=label,
                state_tone=tone,
                last_assessed=timezone.localtime(max(assessed)).date() if assessed else None,
                next_review=approved.next_review_due if approved else None,
                verified=len([c for c in checks if c.state == "verified"]),
                total=len(checks),
            )
        )
    level, state = data.get("level"), data.get("state")
    if level == "none":
        rows = [r for r in rows if not r.level]
    elif level:
        rows = [r for r in rows if r.level == level]
    if state:
        rows = [r for r in rows if r.state_key == state]
    return rows
