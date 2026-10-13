"""The one place that talks to Companies House. See docs/specs/10-integrations.md section 1.

Sign-in is HTTP Basic with the key as the user name and an empty password. The key
is never logged, shown or put in an error message.
"""

import base64
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.company-information.service.gov.uk"
TIMEOUT_SECONDS = 20
# Under two requests a second.
MIN_INTERVAL = 0.55
SERVER_ERROR_RETRIES = 3
# Never wait longer than this for a 429 reset, so a page or job is not stuck for ever.
MAX_RATE_LIMIT_WAIT = 300

COMPANY_NUMBER = re.compile(r"^[A-Z0-9]{8}$")


class CompaniesHouseError(Exception):
    """Something went wrong talking to Companies House. `public_message` is safe to show."""

    public_message = "Companies House could not be reached. Try again later."


class NotFound(CompaniesHouseError):
    public_message = "Companies House has no company with that number."


class AuthFailed(CompaniesHouseError):
    public_message = "Companies House refused the API key. Check COMPANIES_HOUSE_API_KEY."


class RateLimited(CompaniesHouseError):
    public_message = "Companies House asked us to slow down. Try again in a few minutes."


class ServiceError(CompaniesHouseError):
    public_message = "Companies House is not answering properly. Try again later."


class InvalidNumber(CompaniesHouseError):
    public_message = "A company number is up to eight letters and digits, such as 01234567."


def normalise_number(raw: str) -> str:
    """Eight characters, upper case, padded with zeros after any letter prefix.

    "1234" becomes "00001234" and "sc1234" becomes "SC001234".
    """
    text = re.sub(r"\s+", "", raw or "").upper()
    match = re.fullmatch(r"([A-Z]{0,2})(\d{1,8})", text)
    if not match:
        raise InvalidNumber(raw)
    prefix, digits = match.groups()
    number = prefix + digits.zfill(8 - len(prefix))
    if not COMPANY_NUMBER.match(number):
        raise InvalidNumber(raw)
    return number


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


Transport = Callable[[str, dict], Response]


def urllib_transport(url: str, headers: dict) -> Response:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - fixed https base
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:  # noqa: S310
            return Response(reply.status, dict(reply.headers), reply.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers or {}), error.read() or b"")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise CompaniesHouseError(type(error).__name__) from None


# Shared by every client in this process, so pacing holds across calls.
_pace_lock = threading.Lock()
_last_call = [0.0]


class CompaniesHouseClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        min_interval: float = MIN_INTERVAL,
    ):
        self._key = settings.COMPANIES_HOUSE_API_KEY if api_key is None else api_key
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._wall_clock = wall_clock
        self._min_interval = min_interval
        self.calls = 0

    def __repr__(self) -> str:  # never show the key
        return f"<CompaniesHouseClient key={'set' if self._key else 'none'}>"

    # ------------------------------------------------------------ the five calls

    def search(self, text: str, items: int = 10) -> list[dict]:
        text = (text or "").strip()
        if not text:
            return []
        data = self._get("/search/companies", {"q": text, "items_per_page": items})
        return data.get("items", [])[:items]

    def profile(self, number: str) -> dict:
        return self._get(f"/company/{self._number(number)}")

    def officers(self, number: str) -> list[dict]:
        return self._get_list(f"/company/{self._number(number)}/officers")

    def owners(self, number: str) -> list[dict]:
        return self._get_list(f"/company/{self._number(number)}/persons-with-significant-control")

    def filings(self, number: str, items: int = 25) -> list[dict]:
        data = self._get(
            f"/company/{self._number(number)}/filing-history", {"items_per_page": items}
        )
        return data.get("items", [])

    # ------------------------------------------------------------ plumbing

    @staticmethod
    def _number(number: str) -> str:
        return quote(normalise_number(number), safe="")

    def _get_list(self, path: str, page_size: int = 100, limit: int = 500) -> list[dict]:
        """Every item of a paged list, up to `limit`. A list Companies House has none for is []."""
        items: list[dict] = []
        while len(items) < limit:
            try:
                data = self._get(path, {"items_per_page": page_size, "start_index": len(items)})
            except NotFound:
                break  # a company with no owners register answers 404
            page = data.get("items") or []
            items += page
            total = data.get("total_results", len(items))
            if not page or len(items) >= total:
                break
        return items

    def _headers(self) -> dict:
        headers = {"Accept": "application/json", "User-Agent": "practice-manager"}
        if self._key:
            token = base64.b64encode(f"{self._key}:".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _pace(self) -> None:
        with _pace_lock:
            wait = _last_call[0] + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            _last_call[0] = self._clock()

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = BASE_URL + path + (f"?{urlencode(params)}" if params else "")
        server_errors = 0
        rate_limits = 0
        while True:
            self._pace()
            self.calls += 1
            response = self._transport(url, self._headers())
            status = response.status
            if status == 200:
                try:
                    return json.loads(response.body or b"{}")
                except ValueError:
                    raise ServiceError("not JSON") from None
            if status == 404:
                raise NotFound(path)
            if status in (401, 403):
                raise AuthFailed(status)
            if status == 429:
                rate_limits += 1
                if rate_limits > 3:
                    raise RateLimited(status)
                self._sleep(self._reset_wait(response.headers))
                continue
            if status >= 500:
                server_errors += 1
                if server_errors > SERVER_ERROR_RETRIES:
                    raise ServiceError(status)
                self._sleep(2**server_errors)  # 2, 4, 8 seconds
                continue
            raise CompaniesHouseError(status)

    def _reset_wait(self, headers: dict) -> float:
        """Seconds until the rate limit resets, from X-Ratelimit-Reset (a Unix time)."""
        lowered = {k.lower(): v for k, v in headers.items()}
        try:
            reset = float(lowered.get("x-ratelimit-reset", ""))
        except ValueError:
            return 60.0
        return min(max(reset - self._wall_clock(), 1.0), MAX_RATE_LIMIT_WAIT)


def key_present() -> bool:
    return bool(settings.COMPANIES_HOUSE_API_KEY)


def get_client() -> CompaniesHouseClient:
    """The live client, or the fake when settings say so (tests and CI)."""
    if settings.COMPANIES_HOUSE_TRANSPORT == "fake":
        from .fake import fake_client

        return fake_client()
    return CompaniesHouseClient()
