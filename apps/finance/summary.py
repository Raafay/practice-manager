"""The owner summary: written by rules from the data, shown as a page and sent by email.

Owner only. Every figure here is practice-wide money or work, so callers check finance.owner
(the page, the Overview panels) and the email goes only to people who hold it.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.aml.models import IdentityCheck, RiskAssessment
from apps.clients.models import Client
from apps.core.money import format_money
from apps.onboarding.models import AgentAuthorisation
from apps.pipeline import services as pipeline_services
from apps.pipeline.models import Proposal, ProspectDetails
from apps.portal.models import Request
from apps.services.models import Deadline
from apps.tasks.models import Task
from apps.timekeeping.models import TimeEntry

from . import fees, forecast, invoicing
from .models import FinanceSettings
from .sync import owners

SOON_DAYS = 30


def week_range(today: date) -> tuple[date, date]:
    """Monday to today."""
    return today - timedelta(days=today.weekday()), today


def deadlines_section(today: date) -> dict:
    open_deadlines = Deadline.objects.open().exclude(
        client__status__in=(Client.Status.FORMER, Client.Status.LOST)
    )
    overdue = open_deadlines.filter(due_date__lt=today)
    soon = open_deadlines.filter(due_date__gte=today, due_date__lte=today + timedelta(days=14))

    def by_service(queryset):
        rows = queryset.values("client_service__service__name").annotate(n=Count("id"))
        return sorted(
            ((r["client_service__service__name"] or "Other", r["n"]) for r in rows),
            key=lambda kv: (-kv[1], kv[0]),
        )

    return {
        "overdue": overdue.count(),
        "overdue_by_service": by_service(overdue),
        "soon": soon.count(),
        "soon_by_service": by_service(soon),
    }


def work_section(today: date) -> dict:
    first, _ = week_range(today)
    done = Task.objects.live().filter(completed_at__date__gte=first, completed_at__date__lte=today)
    overdue = Task.objects.open().filter(
        Q(target_date__lt=today) | Q(target_date__isnull=True, due_date__lt=today)
    )
    done_by = Counter(done.values_list("owner__name", flat=True))
    overdue_by = Counter(overdue.values_list("owner__name", flat=True))
    return {
        "completed": done.count(),
        "overdue": overdue.count(),
        "completed_by": sorted(
            ((k or "Unassigned", v) for k, v in done_by.items()), key=lambda kv: -kv[1]
        ),
        "overdue_by": sorted(
            ((k or "Unassigned", v) for k, v in overdue_by.items()), key=lambda kv: -kv[1]
        ),
    }


def requests_section(today: date) -> dict:
    first, _ = week_range(today)
    open_states = (Request.State.NEW, Request.State.IN_PROGRESS)
    still_open = Request.objects.filter(state__in=open_states)
    oldest = still_open.order_by("created_at").first()
    return {
        "received": Request.objects.filter(created_at__date__gte=first)
        .exclude(state="spam")
        .count(),
        "open": still_open.count(),
        "oldest_days": (today - timezone.localtime(oldest.created_at).date()).days
        if oldest
        else None,
    }


def sales_section(today: date) -> dict:
    first, _ = week_range(today)
    quiet = pipeline_services.quiet_prospects(today=today)
    return {
        "enquiries": ProspectDetails.objects.filter(
            enquiry_date__gte=first, enquiry_date__lte=today
        ).count(),
        "moves": ProspectDetails.objects.filter(stage_changed_at__date__gte=first).count(),
        "proposals_sent": Proposal.objects.filter(sent_at__date__gte=first).count(),
        "won": ProspectDetails.objects.filter(won_on__gte=first, won_on__lte=today).count(),
        "lost": ProspectDetails.objects.filter(lost_on__gte=first, lost_on__lte=today).count(),
        "quiet": len(quiet),
    }


def compliance_section(today: date) -> dict:
    soon = today + timedelta(days=SOON_DAYS)
    return {
        "onboarding": Client.objects.filter(status=Client.Status.ONBOARDING).count(),
        "aml_reviews": RiskAssessment.objects.filter(
            state=RiskAssessment.State.APPROVED, next_review_due__lte=soon
        ).count(),
        "id_expiring": IdentityCheck.objects.filter(
            excluded=False, document_expiry__isnull=False, document_expiry__lte=soon
        ).count(),
        "hmrc_expiring": AgentAuthorisation.objects.filter(
            Q(code_expires_on__range=(today, soon)) | Q(link_expires_on__range=(today, soon))
        )
        .exclude(state__in=("authorised", "expired"))
        .count(),
    }


def money_section(today: date, *, snap=None, targets=None) -> dict:
    snap = snap or forecast.gather(today)
    targets = targets if targets is not None else forecast.target_map()
    month = forecast.first_of(today)
    this = fees.summary().total
    last_week = today - timedelta(days=7)
    week_changes = _fee_change_since(last_week)
    invoiced = invoicing.invoiced_in_month(month)
    contracted = forecast.contracted(snap, month)
    next_month = forecast.first_of(today + timedelta(days=32))
    row = forecast.month_row(snap, targets, next_month)
    lines = forecast.feedback(snap, row, today=today).lines[:3]
    return {
        "recurring": this,
        "week_change": week_changes,
        "week_down": -week_changes,
        "invoiced": invoiced,
        "contracted": contracted,
        "has_xero": invoicing.has_xero_data(),
        "overdue": invoicing.overdue_total(today),
        "overdue_count": len(invoicing.overdue_groups(today)),
        "next_month": next_month,
        "lines": lines,
    }


def _fee_change_since(since: date) -> Decimal:
    from apps.services.models import FeeChange

    total = Decimal("0.00")
    for change in FeeChange.objects.filter(effective_on__gt=since).select_related("client_service"):
        kind, amount = fees.classify_change(change)
        if kind:
            total += amount
    return total


def people_section(today: date) -> list[dict]:
    first, _ = week_range(today)
    logged = dict(
        TimeEntry.objects.filter(date__range=(first, today))
        .values_list("user_id")
        .annotate(t=Sum("minutes"))
    )
    rows = []
    for user in User.objects.staff().filter(is_active=True).order_by("name"):
        minutes = logged.get(user.pk, 0)
        capacity = Decimal(user.weekly_hours) * 60
        rows.append(
            {
                "name": user.name,
                "hours": (Decimal(minutes) / 60).quantize(Decimal("0.1")),
                "capacity": Decimal(user.weekly_hours),
                "percent": int(Decimal(minutes) * 100 / capacity) if capacity else None,
            }
        )
    return rows


def build(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    return {
        "today": today,
        "week_start": week_range(today)[0],
        "deadlines": deadlines_section(today),
        "work": work_section(today),
        "requests": requests_section(today),
        "sales": sales_section(today),
        "compliance": compliance_section(today),
        "money": money_section(today),
        "people": people_section(today),
    }


# ---------------------------------------------------------------- plain text (the email)


def _by(pairs) -> str:
    return ", ".join(f"{name} {n}" for name, n in pairs) or "none"


def as_text(data: dict) -> str:
    d, w, r, s, c, m = (
        data["deadlines"],
        data["work"],
        data["requests"],
        data["sales"],
        data["compliance"],
        data["money"],
    )
    lines = [f"Owner summary for the week from {data['week_start']:%d/%m/%Y}", ""]
    lines += [
        "DEADLINES",
        f"Overdue: {d['overdue']} ({_by(d['overdue_by_service'])})",
        f"Due in the next 14 days: {d['soon']} ({_by(d['soon_by_service'])})",
        "",
    ]
    lines += [
        "WORK",
        f"Tasks completed this week: {w['completed']} ({_by(w['completed_by'])})",
        f"Tasks overdue: {w['overdue']} ({_by(w['overdue_by'])})",
        "",
    ]
    oldest = f", oldest {r['oldest_days']} days" if r["oldest_days"] is not None else ""
    lines += [
        "REQUESTS",
        f"Received this week: {r['received']}. Still open: {r['open']}{oldest}.",
        "",
    ]
    lines += [
        "SALES",
        f"New enquiries: {s['enquiries']}. Stage moves: {s['moves']}. "
        f"Proposals sent: {s['proposals_sent']}. Won: {s['won']}. Lost: {s['lost']}. "
        f"Quiet prospects: {s['quiet']}.",
        "",
    ]
    lines += [
        "COMPLIANCE",
        f"Onboarding in progress: {c['onboarding']}. "
        f"AML reviews due in 30 days: {c['aml_reviews']}. "
        f"Identity documents expiring: {c['id_expiring']}. "
        f"HMRC authorisations expiring: {c['hmrc_expiring']}.",
        "",
    ]
    change = m["week_change"]
    sign = "+" if change >= 0 else "-"
    lines += [
        "MONEY",
        f"Recurring fees now: {format_money(m['recurring'])} "
        f"({sign}{format_money(abs(change))} this week).",
    ]
    if m["has_xero"]:
        lines.append(
            f"Invoiced this month: {format_money(m['invoiced'])} against "
            f"{format_money(m['contracted'])} contracted."
        )
    lines.append(f"Overdue fees: {format_money(m['overdue'])} from {m['overdue_count']} client(s).")
    lines += [*m["lines"], ""]
    lines += ["PEOPLE"]
    for p in data["people"]:
        pct = f" ({p['percent']}%)" if p["percent"] is not None else ""
        lines.append(f"{p['name']}: {p['hours']} of {p['capacity']:.1f} hours{pct}")
    return "\n".join(lines)


def send_owner_summary(now=None, *, force: bool = False) -> dict:
    """Email the summary to the owners, once on the chosen day, from the chosen hour.

    Sent straight to the owners (it is internal, not a client message), never to anyone who
    does not hold finance.owner. Safe to run every hour: it records the day it last sent.
    """
    config = FinanceSettings.load()
    moment = timezone.localtime(now or timezone.now())
    today = moment.date()
    if not force:
        if moment.weekday() != config.summary_weekday or moment.hour < config.summary_hour:
            return {"sent": 0, "reason": "not the time yet"}
        if config.summary_last_sent_on == today:
            return {"sent": 0, "reason": "already sent today"}
    recipients = [u.email for u in owners() if u.email]
    if not recipients:
        return {"sent": 0, "reason": "no owners"}
    data = build(today)
    body = as_text(data)
    sent = 0
    for address in recipients:
        sent += send_mail(
            f"Owner summary: week of {data['week_start']:%d/%m/%Y}",
            body,
            django_settings.DEFAULT_FROM_EMAIL,
            [address],
        )
    FinanceSettings.objects.filter(pk=config.pk).update(summary_last_sent_on=today)
    return {"sent": sent}
