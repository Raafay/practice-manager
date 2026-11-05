"""The one place that talks to Creditsafe Connect. Built against made-up samples in
tests/samples; check the field names against Creditsafe's documentation before go-live.

Sign-in: POST /authenticate with the username and password gives a token for about an hour.
Each company report costs money, so reports are fetched only when someone presses
"Check credit" or when a monitoring alert says something changed.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings

BASE_URL = "https://connect.creditsafe.com/v1"
TIMEOUT = 30
TOKEN_SECONDS = 50 * 60


class CreditsafeError(Exception):
    public_message = "Creditsafe could not be reached. Try again later."


class NotConfigured(CreditsafeError):
    public_message = "Creditsafe is not set up. Add CREDITSAFE_USERNAME and CREDITSAFE_PASSWORD."


class AuthFailed(CreditsafeError):
    public_message = "Creditsafe refused the sign-in. Check the username and password."


class NotFound(CreditsafeError):
    public_message = "Creditsafe has no company with that number."


@dataclass
class Response:
    status: int
    body: bytes

    def json(self):
        return json.loads(self.body or b"{}")


def urllib_transport(method, url, headers=None, body=None) -> Response:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310 - fixed https base
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:  # noqa: S310
            return Response(reply.status, reply.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read())
    except (urllib.error.URLError, TimeoutError) as error:
        raise CreditsafeError from error


def configured() -> bool:
    return bool(settings.CREDITSAFE_USERNAME and settings.CREDITSAFE_PASSWORD)


def _money(value) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_report(data: dict) -> dict:
    """Score, band and limit from a company credit report."""
    report = (data or {}).get("report") or {}
    current = (report.get("creditScore") or {}).get("currentCreditRating") or {}
    provider = current.get("providerValue") or {}
    limit = current.get("creditLimit") or {}
    try:
        score = int(provider.get("value")) if provider.get("value") not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    return {
        "connect_id": report.get("companyId") or "",
        "score": score,
        "rating": (current.get("commonValue") or "")[:4],
        "rating_description": (current.get("commonDescription") or "")[:100],
        "credit_limit": _money(limit.get("value")),
        "currency": (limit.get("currency") or "")[:3],
    }


class Creditsafe:
    def __init__(self, transport=None):
        self.transport = transport or urllib_transport
        self._token = ""
        self._token_at = 0.0
        self.calls = 0

    def __repr__(self) -> str:  # never show the token
        return "<Creditsafe>"

    def _sign_in(self) -> str:
        if not configured():
            raise NotConfigured
        if self._token and time.monotonic() - self._token_at < TOKEN_SECONDS:
            return self._token
        reply = self.transport(
            "POST",
            f"{BASE_URL}/authenticate",
            headers={"Content-Type": "application/json"},
            body={
                "username": settings.CREDITSAFE_USERNAME,
                "password": settings.CREDITSAFE_PASSWORD,
            },
        )
        if reply.status != 200:
            raise AuthFailed
        self._token = reply.json().get("token", "")
        self._token_at = time.monotonic()
        return self._token

    def _get(self, path: str, params: dict | None = None, *, method="GET", body=None):
        token = self._sign_in()
        url = f"{BASE_URL}/{path}" + (f"?{urlencode(params)}" if params else "")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        reply = self.transport(method, url, headers=headers, body=body)
        self.calls += 1
        if reply.status in (200, 201):
            return reply.json()
        if reply.status == 404:
            raise NotFound
        if reply.status in (401, 403):
            raise AuthFailed
        raise CreditsafeError

    def find_company(self, company_number: str) -> str:
        """The Creditsafe id for a UK company number. Searching is free."""
        data = self._get("companies", {"countries": "GB", "regNo": company_number})
        companies = data.get("companies") or []
        if not companies:
            raise NotFound
        return companies[0].get("id", "")

    def report(self, connect_id: str) -> dict:
        """The credit report. This is the call that costs money."""
        return parse_report(self._get(f"companies/{connect_id}", {"language": "en"}))

    def monitor(self, connect_id: str) -> None:
        portfolio = settings.CREDITSAFE_PORTFOLIO_ID
        if portfolio:
            self._get(
                f"monitoring/portfolios/{portfolio}/companies",
                method="POST",
                body={"id": connect_id, "personalReference": "", "freeText": ""},
            )

    def alerts(self, since: str | None = None) -> list[dict]:
        """Monitoring events since an ISO time: [{connect_id, at, description}]."""
        params = {"pageSize": 100}
        if since:
            params["startDate"] = since
        data = self._get("monitoring/notificationEvents", params)
        return [
            {
                "connect_id": (e.get("company") or {}).get("id", ""),
                "at": e.get("eventDate", ""),
                "description": (e.get("ruleName") or e.get("eventType") or "")[:200],
            }
            for e in data.get("data") or []
        ]
