"""The finance assistant: the owner asks in plain English, Claude answers from our figures.

Claude never does the arithmetic. It picks one of the planning functions below, passes
parameters, and explains the figures they return, so every number can be repeated.
Read-only: no tool changes data. Owner only (finance.owner). Each question records the
tokens it used, so usage can be metered.

Needs ANTHROPIC_API_KEY. Company names and fee figures are sent to Anthropic; people who
are clients in their own name are sent as a reference only (planning.client_label).
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from apps import events

from . import planning
from .models import AssistantMessage

MAX_TOOL_ROUNDS = 8
HISTORY_TURNS = 6
# Dollars per million tokens for the default model (input, output, cache read, cache write).
PRICES = {"claude-opus-5-5": (Decimal("4"), Decimal("20"), Decimal("0.20"), Decimal("5"))}

SYSTEM = """You are the finance assistant inside an accountancy practice's management system.
You speak to the practice owner. Amounts are pounds, excluding VAT, per month unless said.

Never calculate figures yourself. Every number you state must come from a tool result in
this conversation. If the owner asks something the tools cannot answer, say so plainly and
say what data would be needed. When the owner states a target ("I want £8k profit a
month", "a 40% margin"), pass it to get_position as target_profit or
target_margin_percent; for "what if" questions use
run_scenario, once per scenario.

Answer like a short management note: a one-line headline, then the key figures as a small
table or list, then one or two sentences on what it means (gap to target, clients needed,
margin, concentration risk). Mention when profit and loss figures are missing or when the
costs are a run-rate average rather than a forecast. Use UK English and £ with commas."""


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS = [
    {
        "name": "get_position",
        "description": "Current monthly fees, cost run rate, profit and margin, against this "
        "month's fee, profit and margin targets: the gap to each and how many clients at the "
        "average new-client fee close it. target_profit (pounds) and target_margin_percent "
        "default to this month's saved targets.",
        "input_schema": _obj(
            {
                "target_profit": {"type": "number", "minimum": 0},
                "target_margin_percent": {"type": "number", "minimum": 0, "maximum": 99},
            }
        ),
    },
    {
        "name": "run_scenario",
        "description": "Monthly profit and margin if new_clients start at fee each (default: "
        "the average new-client fee), optionally losing some monthly fees or adding costs.",
        "input_schema": _obj(
            {
                "new_clients": {"type": "integer", "minimum": 0, "maximum": 500},
                "fee": {"type": "number", "minimum": 0},
                "lost_monthly_fees": {"type": "number", "minimum": 0},
                "extra_monthly_costs": {"type": "number", "minimum": 0},
            },
            ["new_clients"],
        ),
    },
    {
        "name": "forecast_against_actual",
        "description": "Month by month: fee and profit targets, forecast fees and profit, and "
        "for past months the actual income, costs and profit from Xero.",
        "input_schema": _obj(
            {
                "months_back": {"type": "integer", "minimum": 0, "maximum": 24},
                "months_ahead": {"type": "integer", "minimum": 0, "maximum": 12},
            }
        ),
    },
    {
        "name": "margin_trend",
        "description": "Income, net profit and margin for each complete past month.",
        "input_schema": _obj({"months": {"type": "integer", "minimum": 1, "maximum": 36}}),
    },
    {
        "name": "client_concentration",
        "description": "Each client's share of monthly fees, largest first, with warnings for "
        "any client at 25% or more.",
        "input_schema": _obj({"top": {"type": "integer", "minimum": 1, "maximum": 50}}),
    },
    {
        "name": "pipeline_summary",
        "description": "Open prospects, weighted expected monthly fees, proposals waiting and "
        "won/lost in the last 12 months.",
        "input_schema": _obj({}),
    },
]


def _dec(value, name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a number.") from None


def run_tool(name: str, args: dict):
    """Run one planning function with checked arguments. Raises ValueError on bad input."""
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object.")
    if name == "get_position":
        target = args.get("target_profit")
        margin = args.get("target_margin_percent")
        if margin is not None and not (0 <= _dec(margin, "target_margin_percent") < 100):
            raise ValueError("target_margin_percent must be between 0 and 99.")
        return planning.position(
            None if target is None else _dec(target, "target_profit"),
            target_margin=None if margin is None else _dec(margin, "target_margin_percent"),
        )
    if name == "run_scenario":
        fee = args.get("fee")
        return planning.scenario(
            int(args.get("new_clients", 0)),
            None if fee is None else _dec(fee, "fee"),
            _dec(args.get("lost_monthly_fees", 0), "lost_monthly_fees"),
            _dec(args.get("extra_monthly_costs", 0), "extra_monthly_costs"),
        )
    if name == "forecast_against_actual":
        back = min(max(int(args.get("months_back", 6)), 0), 24)
        ahead = min(max(int(args.get("months_ahead", 6)), 0), 12)
        return planning.forecast_against_actual(back, ahead)
    if name == "margin_trend":
        return planning.margin_trend(min(max(int(args.get("months", 12)), 1), 36))
    if name == "client_concentration":
        return planning.concentration(min(max(int(args.get("top", 10)), 1), 50))
    if name == "pipeline_summary":
        return planning.pipeline()
    raise ValueError(f"Unknown tool {name}.")


def is_configured() -> bool:
    return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))


def model_name() -> str:
    return getattr(settings, "FINANCE_ASSISTANT_MODEL", "") or "claude-opus-5-5"


def make_client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=120.0, max_retries=2)


def _history(conversation) -> list[dict]:
    turns = list(
        AssistantMessage.objects.filter(conversation=conversation, failed=False).order_by(
            "-created_at", "-id"
        )[:HISTORY_TURNS]
    )
    messages = []
    for turn in reversed(turns):
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer or "(no answer)"})
    return messages


def ask(user, question: str, conversation=None, client=None) -> AssistantMessage:
    """Ask one question. Always returns the saved AssistantMessage (failed=True on error)."""
    import anthropic

    question = (question or "").strip()[:2000]
    conversation = conversation or uuid.uuid4()
    record = AssistantMessage(
        conversation=conversation, user=user, question=question, model=model_name()
    )
    messages = _history(conversation) + [{"role": "user", "content": question}]
    client = client or make_client()
    tools_used = []
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = client.beta.messages.create(
                model=model_name(),
                max_tokens=16000,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
                cache_control={"type": "ephemeral"},
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            _add_usage(record, response)
            if response.stop_reason == "refusal":
                record.answer = "The assistant could not answer that question."
                break
            if response.stop_reason != "tool_use":
                record.answer = "\n\n".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                break
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append({"name": block.name, "input": block.input})
                try:
                    output = run_tool(block.name, block.input)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(output, default=str),
                        }
                    )
                except (ValueError, TypeError) as error:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(error),
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": results})
        else:
            record.answer = "The assistant took too many steps. Try a narrower question."
    except anthropic.APIError as error:
        record.failed = True
        record.answer = "The assistant is not available just now. Try again in a minute."
        record.tools_used = tools_used
        record.save()
        events.record(
            user,
            "finance.assistant_failed",
            f"The finance assistant failed: {type(error).__name__}.",
            target=record,
        )
        return record
    record.tools_used = tools_used
    record.save()
    events.record(
        user,
        "finance.assistant_asked",
        f"{user} asked the finance assistant a question.",
        target=record,
        tools=[t["name"] for t in tools_used],
    )
    return record


def _add_usage(record: AssistantMessage, response) -> None:
    usage = getattr(response, "usage", None)
    record.calls += 1
    if getattr(response, "model", ""):
        record.model = response.model
    if usage is None:
        return
    record.input_tokens += getattr(usage, "input_tokens", 0) or 0
    record.output_tokens += getattr(usage, "output_tokens", 0) or 0
    record.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
    record.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0


def cost_dollars(record: AssistantMessage) -> Decimal:
    prices = PRICES.get(record.model) or PRICES["claude-opus-5-5"]
    tokens = (
        record.input_tokens,
        record.output_tokens,
        record.cache_read_tokens,
        record.cache_write_tokens,
    )
    total = sum((Decimal(t) * p for t, p in zip(tokens, prices, strict=True)), Decimal("0"))
    return (total / Decimal(1_000_000)).quantize(Decimal("0.0001"))


def usage_this_month(today=None) -> dict:
    today = today or timezone.localdate()
    rows = AssistantMessage.objects.filter(
        created_at__year=today.year, created_at__month=today.month
    )
    return {
        "questions": rows.count(),
        "input_tokens": sum(
            r.input_tokens + r.cache_read_tokens + r.cache_write_tokens for r in rows
        ),
        "output_tokens": sum(r.output_tokens for r in rows),
        "dollars": sum((cost_dollars(r) for r in rows), Decimal("0")).quantize(Decimal("0.01")),
    }
