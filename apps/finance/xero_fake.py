"""A stand-in for Xero that serves the made-up samples. For tests, CI and demo data.

`overrides` replaces the answer for one path. `queue` holds one-off answers served first, so a
test can send a 429 and then a normal page. `requests` records every call.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

from . import xero
from .xero import Response

SAMPLES = Path(__file__).parent / "tests" / "samples"


class FakeXero:
    def __init__(self, samples: Path = SAMPLES):
        self.samples = samples
        self.requests: list[dict] = []
        self.overrides: dict[str, object] = {}
        self.queue: list[Response] = []
        self.token_calls = 0
        self.refresh_delay = 0.0

    def _file(self, name: str):
        return json.loads((self.samples / f"{name}.json").read_text())

    def __call__(self, method, url, headers=None, params=None, form=None, body=None) -> Response:
        path = urlparse(url).path
        self.requests.append(
            {
                "method": method,
                "url": url,
                "path": path,
                "headers": headers or {},
                "params": params or {},
                "form": form,
                "body": body,
            }
        )
        if self.queue:
            return self.queue.pop(0)
        if url == xero.TOKEN_URL:
            return self._token(form or {})
        if url == xero.CONNECTIONS_URL:
            return self._ok(self._file("connections"))
        name = path.rsplit("/", 1)[-1]
        if name in self.overrides:
            return self._ok(self.overrides[name])
        page = int((params or {}).get("page", 1))
        if method == "POST" and name == "Contacts":
            sent = ((body or {}).get("Contacts") or [{}])[0]
            data = self._file("contact_created")
            data["Contacts"][0]["Name"] = sent.get("Name", data["Contacts"][0]["Name"])
            data["Contacts"][0]["EmailAddress"] = sent.get("EmailAddress", "")
            return self._ok(data)
        if name == "Contacts":
            return self._ok(self._file("contacts") if page == 1 else {"Contacts": []})
        if name == "Invoices":
            return self._ok(self._file(f"invoices_page{page}" if page <= 2 else "invoices_page2"))
        if name == "CreditNotes":
            return self._ok(self._file("credit_notes") if page == 1 else {"CreditNotes": []})
        return Response(404, {}, b"{}")

    def _token(self, form: dict) -> Response:
        import time

        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        self.token_calls += 1
        data = self._file("token")
        data["access_token"] = f"access-{self.token_calls}"
        data["refresh_token"] = f"refresh-{self.token_calls}"
        return self._ok(data)

    @staticmethod
    def _ok(data) -> Response:
        return Response(200, {}, json.dumps(data).encode())


def rate_limited(seconds: int = 2) -> Response:
    body = (SAMPLES / "rate_limited.json").read_bytes()
    return Response(429, {"Retry-After": str(seconds)}, body)


_instance: FakeXero | None = None


def fake_transport() -> FakeXero:
    global _instance
    if _instance is None:
        _instance = FakeXero()
    return _instance


def reset() -> None:
    global _instance
    _instance = None
