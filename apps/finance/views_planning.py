"""Finance: the Profit page (targets against actuals, scenarios) and the assistant. Owner only."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from apps import events

from . import assistant, planning
from .models import AssistantMessage, MonthlyResult, ProfitTarget
from .views import FinanceView, _decimal, _int, _month_arg


class ProfitView(FinanceView):
    section = "profit"

    def get(self, request):
        try:
            target = _decimal(request.GET.get("target"))
        except ValueError:
            target = None
        try:
            margin = _decimal((request.GET.get("margin") or "").replace("%", ""))
        except ValueError:
            margin = None
        new_clients = _int(request.GET.get("clients"))
        try:
            fee = _decimal(request.GET.get("fee"))
        except ValueError:
            fee = None
        scenario = None
        if new_clients is not None and 0 <= new_clients <= 500:
            scenario = planning.scenario(new_clients, fee)
        events.record(request.user, "finance.viewed", f"{request.user} opened the Profit page.")
        return self.page(
            request,
            "finance/profit.html",
            {
                "position": planning.position(target, target_margin=margin),
                "scenario": scenario,
                "rows": planning.forecast_against_actual(),
                "concentration": planning.concentration(),
                "trend": planning.margin_trend(),
                "profit_targets": ProfitTarget.objects.filter(month__gte=planning.this_month())[
                    :12
                ],
                "results": MonthlyResult.objects.order_by("-month")[:12],
                "this_month": planning.this_month(),
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        month = _month_arg(request.POST.get("month"), None)
        try:
            if month is None:
                raise ValueError("Choose a month.")
            if action == "target":
                amount = _decimal(request.POST.get("profit"))
                margin = _decimal((request.POST.get("margin") or "").replace("%", ""))
                if margin is not None and not (0 <= margin < 100):
                    raise ValueError("A margin target is a percentage from 0 to 99.")
                if amount is None and margin is None:
                    ProfitTarget.objects.filter(month=month).delete()
                else:
                    ProfitTarget.objects.update_or_create(
                        month=month, defaults={"profit": amount, "margin_percent": margin}
                    )
                what = f"the profit and margin targets for {month:%m/%Y}"
            elif action == "result":
                figures = {
                    k: _decimal(request.POST.get(k)) or Decimal("0")
                    for k in ("income", "cost_of_sales", "overheads")
                }
                net = figures["income"] - figures["cost_of_sales"] - figures["overheads"]
                MonthlyResult.objects.update_or_create(
                    month=month,
                    defaults={**figures, "net_profit": net, "source": MonthlyResult.Source.MANUAL},
                )
                what = f"the profit and loss for {month:%m/%Y}"
            else:
                raise ValueError("Unknown action.")
        except ValueError as error:
            messages.error(request, str(error))
            return redirect("finance:profit")
        events.record(request.user, "finance.changed", f"{request.user} saved {what}.")
        messages.success(request, "Saved.")
        return redirect("finance:profit")


class AssistantView(FinanceView):
    section = "assistant"

    def _conversation(self, request):
        value = request.GET.get("c") or request.POST.get("c") or ""
        try:
            return uuid.UUID(value)
        except ValueError:
            return None

    def get(self, request):
        conversation = self._conversation(request)
        turns = (
            AssistantMessage.objects.filter(conversation=conversation, user=request.user)
            if conversation
            else AssistantMessage.objects.none()
        )
        return self.page(
            request,
            "finance/assistant.html",
            {
                "configured": assistant.is_configured(),
                "conversation": conversation,
                "turns": turns,
                "usage": assistant.usage_this_month(),
                "examples": [
                    "I want £8,000 profit a month. How many more clients do I need?",
                    "What happens if I win four new clients at £350 a month?",
                    "Show forecast against actual for the last six months.",
                    "Which clients make up most of our income?",
                ],
            },
        )

    def post(self, request):
        if not assistant.is_configured():
            messages.error(request, "The assistant is not set up: ANTHROPIC_API_KEY is missing.")
            return redirect("finance:assistant")
        question = (request.POST.get("question") or "").strip()
        conversation = self._conversation(request)
        if (
            conversation is not None
            and not AssistantMessage.objects.filter(
                conversation=conversation, user=request.user
            ).exists()
        ):
            conversation = None
        if not question:
            messages.error(request, "Type a question.")
        else:
            record = assistant.ask(request.user, question, conversation)
            conversation = record.conversation
        url = reverse("finance:assistant")
        return redirect(f"{url}?c={conversation}" if conversation else url)
