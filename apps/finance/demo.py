"""Made-up time, Xero figures and targets for development. Everything here is invented.

Time entries cover the last three months. The Xero data is built in the shape Xero sends (see
tests/samples/) and read through the same code as a real sync, so every Finance page has figures
without a connection. Safe to run twice: demo rows are found by their Xero id or note.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.dates import add_months, is_working_day
from apps.timekeeping.models import TimeEntry

from . import fees, forecast, sync, targets
from .models import FinanceSettings, Target, XeroContact

DEMO_NOTE = "Demo time"
PREFIX = "demo-"


def _id(kind: str, number: int) -> str:
    return f"{PREFIX}{kind}-{number:05d}"


def seed_time(today: date) -> int:
    if TimeEntry.objects.filter(note=DEMO_NOTE).exists():
        return 0
    rng = random.Random(11)  # noqa: S311 - demo data, not security
    people = list(User.objects.staff().filter(is_active=True).order_by("id"))
    clients = list(Client.objects.filter(status="active").order_by("id"))
    if not people or not clients:
        return 0
    made, day = 0, today - timedelta(days=92)
    while day < today:
        if is_working_day(day):
            for person in people:
                if rng.random() < 0.15:
                    continue  # a day off
                hours = rng.choice([6.0, 6.5, 7.0, 7.5])
                remaining = int(hours * 60)
                while remaining > 0:
                    minutes = min(remaining, rng.choice([45, 60, 90, 120, 150]))
                    remaining -= minutes
                    # A small group of clients takes far more time than its fee: the hourly
                    # return page then has something to flag.
                    pool = clients[:4] if rng.random() < 0.25 else clients
                    client = rng.choice(pool) if rng.random() < 0.88 else None
                    TimeEntry.objects.create(
                        user=person,
                        client=client,
                        date=day,
                        minutes=minutes,
                        note=DEMO_NOTE,
                        billable=client is not None,
                    )
                    made += 1
        day += timedelta(days=1)
    return made


def _stamp(day: date) -> str:
    return f"{day.isoformat()}T00:00:00"


def _invoice(number: int, contact, day: date, net: Decimal, *, status: str, due_days: int = 14):
    net = net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = (net * Decimal("0.2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = net + tax
    paid = status == "PAID"
    return {
        "InvoiceID": _id("inv", number),
        "Type": "ACCREC",
        "InvoiceNumber": f"INV-{number:04d}",
        "Reference": f"{day:%B} fee",
        "Contact": {"ContactID": contact.xero_id, "Name": contact.name},
        "DateString": _stamp(day),
        "DueDateString": _stamp(day + timedelta(days=due_days)),
        "Status": status,
        "SubTotal": float(net),
        "TotalTax": float(tax),
        "Total": float(total),
        "AmountDue": 0.0 if paid else float(total),
        "AmountPaid": float(total) if paid else 0.0,
        "AmountCredited": 0.0,
        "CurrencyCode": "GBP",
        "UpdatedDateUTC": f"{day.isoformat()}T09:00:00",
    }


def seed_xero(today: date) -> dict:
    if XeroContact.objects.filter(xero_id__startswith=PREFIX).exists():
        return {"xero_invoices": 0}
    rng = random.Random(23)  # noqa: S311 - demo data, not security
    summary = fees.summary().clients
    invoices = number = 0
    for index, entry in enumerate(summary):
        client = entry["client"]
        contact = sync.upsert_contact(
            {
                "ContactID": _id("contact", index + 1),
                "Name": client.name,
                "EmailAddress": f"accounts{index + 1}@example.com",
                "ContactStatus": "ACTIVE",
            }
        )
        if index % 9 == 8:
            continue  # left for the matching screen
        contact.client = client
        contact.match_state = XeroContact.Match.CONFIRMED
        contact.save()
        for back in range(4, -1, -1):
            month = add_months(today.replace(day=1), -back)
            if back == 0 and (index % 7 == 3):
                continue  # not invoiced this month
            invoice_day = month.replace(day=1) + timedelta(days=rng.choice([0, 1, 2]))
            if invoice_day > today:
                continue
            net = entry["monthly"]
            if back == 0 and index % 5 == 1:
                net = net + Decimal("45")  # differs from the agreed fee
            due = invoice_day + timedelta(days=14)
            unpaid = back <= 1 and index % 4 == 2
            status = "AUTHORISED" if (unpaid or due >= today) else "PAID"
            number += 1
            if sync.upsert_invoice(_invoice(number, contact, invoice_day, net, status=status)):
                invoices += 1
    # One credit note, and a draft that must not count.
    first = XeroContact.objects.filter(xero_id__startswith=PREFIX, client__isnull=False).first()
    if first is not None:
        credit_day = today.replace(day=1) - timedelta(days=10)
        sync.upsert_credit_note(
            {
                "CreditNoteID": _id("cn", 1),
                "Type": "ACCRECCREDIT",
                "CreditNoteNumber": "CN-0001",
                "Contact": {"ContactID": first.xero_id, "Name": first.name},
                "DateString": _stamp(credit_day),
                "Status": "AUTHORISED",
                "SubTotal": 50.0,
                "TotalTax": 10.0,
                "Total": 60.0,
                "RemainingCredit": 60.0,
            }
        )
        number += 1
        sync.upsert_invoice(_invoice(number, first, today, Decimal("999"), status="DRAFT"))
    sync.refresh_suggestions()
    return {"xero_invoices": invoices}


def seed_targets(today: date) -> int:
    """Targets for the next twelve months: a straight line a little above fees today."""
    months = targets.months_from(add_months(today.replace(day=1), 1))
    if Target.objects.filter(month__in=months).exists():
        return 0
    now = fees.summary().total or Decimal("5000")
    amounts = targets.straight_line(now * Decimal("1.04"), now * Decimal("1.30"))
    for month, amount in zip(months, amounts, strict=True):
        Target.objects.create(month=month, amount=amount)
    return len(months)


def seed() -> dict:
    today = timezone.localdate()
    FinanceSettings.load()
    counts = {"time_entries": seed_time(today)}
    counts.update(seed_xero(today))
    counts["targets"] = seed_targets(today)
    forecast.gather(today)  # fail here, not on the page, if the data cannot be read
    return counts
