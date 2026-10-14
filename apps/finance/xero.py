"""The one place that talks to Xero. See docs/specs/10-integrations.md section 3.

OAuth 2.0 authorisation code flow. Access tokens last 30 minutes; the refresh token changes on
every use, so a refresh happens inside a database lock (two processes must not both spend the
same refresh token). Tokens are stored encrypted and never logged or shown. Data calls send
the organisation id in `xero-tenant-id`. On 429 the Retry-After header is obeyed.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import XeroConnection

logger = logging.getLogger(__name__)

AUTHORISE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"
API_BASE = "https://api.xero.com/api.xro/2.0/"
# The narrowest set that works for Apps created since 2 March 2026.
SCOPES = "offline_access accounting.contacts accounting.invoices.read accounting.payments.read"
TIMEOUT_SECONDS = 30
REFRESH_MARGIN = timedelta(minutes=2)
MAX_RETRIES = 3
# Never wait longer than this for a 429 reset: the job is tried again at its next slot.
MAX_RATE_LIMIT_WAIT = 90
PAGE_SIZE = 100


class XeroError(Exception):
    """Something went wrong talking to Xero. `public_message` is safe to show."""

    public_message = "Xero could not be reached. Try again later."


class NotConnected(XeroError):
    public_message = "Xero is not connected. Connect it from Settings, Integrations."


class AuthFailed(XeroError):
    public_message = "Xero refused the connection. Connect Xero again from Settings, Integrations."


class RateLimited(XeroError):
    public_message = "Xero asked us to slow down. The next sync will carry on."


class ServiceError(XeroError):
    public_message = "Xero is not answering properly. Try again later."


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""

    def json(self):
        return json.loads(self.body or b"null")

    def header(self, name: str, default: str = "") -> str:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default


Transport = Callable[..., Response]


def urllib_transport(method, url, headers=None, params=None, form=None, body=None) -> Response:
    if params:
        url = f"{url}?{urlencode(params)}"
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    headers.setdefault("Accept", "application/json")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:  # noqa: S310
            return Response(reply.status, dict(reply.headers), reply.read())
    except urllib.error.HTTPError as failure:
        return Response(failure.code, dict(failure.headers), failure.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ServiceError from None


def default_transport() -> Transport:
    if settings.XERO_TRANSPORT == "fake":
        from .xero_fake import fake_transport

        return fake_transport()
    return urllib_transport


def redirect_uri() -> str:
    return f"{settings.SITE_URL}/integrations/xero/callback"


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorise_url(state: str) -> str:
    query = {
        "response_type": "code",
        "client_id": settings.XERO_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORISE_URL}?{urlencode(query)}"


def keys_present() -> bool:
    return bool(settings.XERO_CLIENT_ID and settings.XERO_CLIENT_SECRET)


def _basic() -> str:
    raw = f"{settings.XERO_CLIENT_ID}:{settings.XERO_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def current_connection() -> XeroConnection | None:
    return XeroConnection.objects.order_by("-id").first()


class XeroClient:
    def __init__(self, transport: Transport | None = None, sleep=time.sleep, now=timezone.now):
        self.transport = transport or default_transport()
        self.sleep = sleep
        self.now = now
        self.calls = 0

    def __repr__(self) -> str:  # never show tokens
        return "<XeroClient>"

    # ------------------------------------------------------------ tokens

    def _token_request(self, form: dict) -> dict:
        reply = self.transport("POST", TOKEN_URL, headers={"Authorization": _basic()}, form=form)
        self.calls += 1
        if reply.status in (400, 401, 403):
            raise AuthFailed
        if reply.status == 429:
            raise RateLimited
        if reply.status >= 500 or reply.status != 200:
            raise ServiceError
        data = reply.json()
        if not data.get("access_token") or not data.get("refresh_token"):
            raise ServiceError
        return data

    def _store_tokens(self, connection: XeroConnection, data: dict) -> None:
        connection.access_token = data["access_token"]
        connection.refresh_token = data["refresh_token"]
        connection.expires_at = self.now() + timedelta(seconds=int(data.get("expires_in", 1800)))
        connection.save(update_fields=["access_token", "refresh_token", "expires_at", "updated_at"])

    def exchange_code(self, code: str, user=None) -> XeroConnection:
        """Finish the consent: swap the code for tokens and note the organisation."""
        data = self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()}
        )
        reply = self.transport(
            "GET", CONNECTIONS_URL, headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        self.calls += 1
        if reply.status != 200:
            raise ServiceError
        tenants = [
            t for t in reply.json() or [] if t.get("tenantType", "ORGANISATION") == "ORGANISATION"
        ]
        if not tenants:
            raise ServiceError
        tenant = tenants[0]
        with transaction.atomic():
            XeroConnection.objects.all().delete()
            connection = XeroConnection.objects.create(
                tenant_id=tenant["tenantId"],
                tenant_name=tenant.get("tenantName", ""),
                connected_by=user,
                connected_at=self.now(),
            )
            self._store_tokens(connection, data)
        return connection

    def access_token(self) -> tuple[str, str]:
        """(access token, tenant id), refreshed first if it is about to run out."""
        connection = current_connection()
        if connection is None or not connection.refresh_token:
            raise NotConnected
        if connection.expires_at and connection.expires_at - REFRESH_MARGIN > self.now():
            return connection.access_token, connection.tenant_id
        return self._refresh(connection.pk)

    def _refresh(self, pk: int) -> tuple[str, str]:
        with transaction.atomic():
            connection = XeroConnection.objects.select_for_update().get(pk=pk)
            # Another process may have refreshed while this one waited for the lock.
            if connection.expires_at and connection.expires_at - REFRESH_MARGIN > self.now():
                return connection.access_token, connection.tenant_id
            data = self._token_request(
                {"grant_type": "refresh_token", "refresh_token": connection.refresh_token}
            )
            self._store_tokens(connection, data)
            return connection.access_token, connection.tenant_id

    # ------------------------------------------------------------ data calls

    def _call(self, method, path, *, params=None, body=None, since: datetime | None = None):
        refreshed = False
        for attempt in range(MAX_RETRIES + 1):
            token, tenant = self.access_token()
            headers = {"Authorization": f"Bearer {token}", "xero-tenant-id": tenant}
            if since is not None:
                headers["If-Modified-Since"] = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
            reply = self.transport(
                method, API_BASE + path, headers=headers, params=params, body=body
            )
            self.calls += 1
            if reply.status == 200:
                return reply.json()
            if reply.status == 401 and not refreshed:
                refreshed = True
                connection = current_connection()
                connection.expires_at = self.now() - timedelta(minutes=1)
                connection.save(update_fields=["expires_at", "updated_at"])
                continue
            if reply.status in (401, 403):
                raise AuthFailed
            if reply.status == 429:
                wait = _retry_after(reply)
                if attempt >= MAX_RETRIES or wait > MAX_RATE_LIMIT_WAIT:
                    raise RateLimited
                self.sleep(wait)
                continue
            if reply.status >= 500 and attempt < MAX_RETRIES:
                self.sleep(2**attempt)
                continue
            raise ServiceError
        raise ServiceError

    def pages(self, path: str, key: str, *, where: str = "", since=None):
        """Every item of a paged list. Stops at the page count Xero reports, or an empty page."""
        page = 1
        while True:
            params = {"page": page, "pageSize": PAGE_SIZE}
            if where:
                params["where"] = where
            data = self._call("GET", path, params=params, since=since) or {}
            items = data.get(key) or []
            yield from items
            count = (data.get("pagination") or {}).get("pageCount")
            if not items or (count is not None and page >= count):
                return
            page += 1

    def contacts(self, since=None):
        return self.pages("Contacts", "Contacts", where="IsCustomer==true", since=since)

    def invoices(self, since=None):
        return self.pages("Invoices", "Invoices", where='Type=="ACCREC"', since=since)

    def credit_notes(self, since=None):
        return self.pages("CreditNotes", "CreditNotes", where='Type=="ACCRECCREDIT"', since=since)

    def create_contact(self, name: str, email: str = "") -> dict:
        """The one write: make a contact. Returns Xero's contact."""
        contact = {"Name": name}
        if email:
            contact["EmailAddress"] = email
        data = self._call("POST", "Contacts", body={"Contacts": [contact]})
        created = (data or {}).get("Contacts") or []
        if not created:
            raise ServiceError
        return created[0]


def _retry_after(reply: Response) -> int:
    try:
        return max(int(float(reply.header("Retry-After", "1"))), 1)
    except ValueError:
        return 1
