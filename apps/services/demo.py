"""Made-up services, fees and deadlines for development. Everything here is invented.

Safe to run twice: a client that already has a service is left alone. Dates are set
relative to today so the Deadlines report always shows a spread: some overdue, some
due soon, some further out.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.clients.models import Client

from . import deadlines
from .models import ClientService, Deadline, FeeChange, Service

S = Client.Status


def _fee(code: str, index: int) -> tuple[Decimal, str]:
    base = {
        "accounts": (Decimal("95"), "monthly"),
        "ct600": (Decimal("420"), "annual"),
        "confirmation": (Decimal("75"), "annual"),
        "bookkeeping": (Decimal("140"), "monthly"),
        "vat": (Decimal("270"), "quarterly"),
        "payroll": (Decimal("60"), "monthly"),
        "auto_enrolment": (Decimal("180"), "annual"),
        "management_accounts": (Decimal("240"), "monthly"),
        "cis": (Decimal("45"), "monthly"),
        "p11d": (Decimal("150"), "annual"),
        "fee_protection": (Decimal("360"), "annual"),
        "self_assessment": (Decimal("280"), "annual"),
        "mtd_income_tax": (Decimal("35"), "monthly"),
        "partnership_return": (Decimal("320"), "annual"),
        "registered_office": (Decimal("60"), "annual"),
        "fractional_fd": (Decimal("1200"), "monthly"),
    }
    amount, frequency = base[code]
    return amount + Decimal(index % 5) * 5, frequency


def _codes(client: Client, index: int) -> list[str]:
    kind = client.client_type
    if kind in ("ltd", "plc"):
        codes = ["accounts", "ct600", "confirmation"]
        if index % 2 == 0:
            codes.append("bookkeeping")
        if client.vat_frequency:
            codes.append("vat")
        if client.payroll_frequency:
            codes += ["payroll", "auto_enrolment"]
        if index % 5 == 0:
            codes.append("management_accounts")
        if index % 6 == 0:
            codes.append("fee_protection")
        if index % 7 == 0:
            codes.append("registered_office")
        if index % 9 == 0:
            codes.append("fractional_fd")
        return codes
    if kind == "llp":
        codes = ["accounts", "confirmation", "bookkeeping"]
        return codes + (["vat"] if client.vat_frequency else [])
    if kind == "partnership":
        return ["partnership_return", "bookkeeping"]
    if kind in ("sole_trader", "individual"):
        codes = ["mtd_income_tax" if client.mtd_start == "2026-04" else "self_assessment"]
        return codes + (["bookkeeping"] if kind == "sole_trader" else [])
    return ["bookkeeping"]


def _settings(code: str, index: int) -> dict:
    if code == "bookkeeping":
        return {"frequency": "monthly", "due_days": 14}
    if code == "management_accounts":
        return {"frequency": "quarterly", "end_month": 3, "due_days": 20}
    if code == "fee_protection":
        return {
            "frequency": "annual",
            "end_month": 11,
            "end_day": 20,
            "due_days": 0,
            "renewal": True,
        }
    if code == "registered_office":
        return {
            "frequency": "annual",
            "end_month": 12,
            "end_day": 1,
            "due_days": 0,
            "renewal": True,
        }
    if code == "payroll":
        return {"paye_quarterly": index % 4 == 0}
    return {}


def _adjust_dates(client: Client, slot: int, today: date) -> None:
    """Move a company's Companies House dates so the report shows a spread."""
    end = [
        today - timedelta(days=100),
        today - timedelta(days=30),
        today - timedelta(days=60),
        today + timedelta(days=120),
    ][slot % 4]
    due = [
        today - timedelta(days=8),
        today + timedelta(days=9),
        today + timedelta(days=40),
        today + timedelta(days=200),
    ][slot % 4]
    client.last_accounts_made_up_to = end - timedelta(days=365)
    client.next_accounts_made_up_to = end
    client.next_accounts_due = due
    client.next_statement_made_up_to = today + timedelta(days=[5, 20, 70, 150][slot % 4])
    client.next_statement_due = client.next_statement_made_up_to + timedelta(days=14)
    client.save()


def seed(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    catalogue = {s.code: s for s in Service.objects.all()}
    made = 0
    generated = 0
    clients = Client.objects.exclude(status__in=[S.PROSPECT, S.LOST]).order_by("name")
    index = 0
    for client in clients:
        index += 1
        if client.client_services.exists():
            continue
        live = client.status in (S.ACTIVE, S.PAUSED)
        if client.is_company and client.company_number and live and client.status == S.ACTIVE:
            _adjust_dates(client, index, today)
        for code in _codes(client, index):
            service = catalogue.get(code)
            if service is None or not service.applies_to_type(client.client_type):
                continue
            amount, frequency = _fee(code, index)
            if client.status == S.FORMER:
                state, ends_on = ClientService.State.ENDED, client.relationship_ended_on
            elif client.status == S.ONBOARDING:
                state, ends_on = ClientService.State.PROPOSED, None
            else:
                state, ends_on = ClientService.State.ACTIVE, None
            cs = ClientService.objects.create(
                client=client,
                service=service,
                state=state,
                fee_amount=amount,
                fee_frequency=frequency,
                starts_on=None if state == "proposed" else today - timedelta(days=400),
                ends_on=ends_on,
                settings=_settings(code, index),
            )
            FeeChange.objects.create(
                client_service=cs,
                new_amount=amount,
                new_frequency=frequency,
                effective_on=today - timedelta(days=400),
                reason="Demo data",
            )
            made += 1
        if client.status == S.ACTIVE:
            generated += len(deadlines.generate_for_client(client, today=today).created)
    # Older work is finished, so only the most recent dates are overdue.
    finished = Deadline.objects.filter(
        status="open", due_date__lt=today - timedelta(days=20)
    ).exclude(source="companies_house")
    for deadline in finished:
        deadline.status = Deadline.Status.DONE
        deadline.done_on = deadline.due_date - timedelta(days=2)
        deadline.done_note = "Filed (demo)"
        deadline.save()
    return {"client_services": made, "deadlines": generated}
