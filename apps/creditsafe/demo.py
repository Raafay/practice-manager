"""Made-up credit ratings for a few demo companies, including one that fell."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.clients.models import Client

from .models import CreditCheck

HISTORY = [("B", 74, "A", 81), ("C", 48, "B", 70), ("A", 88, None, None)]


def seed() -> dict:
    if CreditCheck.objects.exists():
        return {"credit_checks": 0}
    companies = Client.objects.exclude(company_number="").order_by("pk")[: len(HISTORY)]
    made = 0
    for client, (rating, score, old_rating, old_score) in zip(companies, HISTORY, strict=False):
        if old_rating:
            old = CreditCheck.objects.create(
                client=client, company_number=client.company_number, rating=old_rating,
                score=old_score, credit_limit=Decimal("20000"), currency="GBP",
                source=CreditCheck.Source.DEMO, rating_description="Demo",
            )  # fmt: skip
            CreditCheck.objects.filter(pk=old.pk).update(
                created_at=timezone.now() - timedelta(days=60)
            )
            made += 1
        CreditCheck.objects.create(
            client=client, company_number=client.company_number, rating=rating, score=score,
            credit_limit=Decimal("15000"), currency="GBP", source=CreditCheck.Source.DEMO,
            rating_description="Demo",
        )  # fmt: skip
        made += 1
    return {"credit_checks": made}
