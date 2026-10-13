"""A stand-in for Companies House that serves the made-up samples. For tests and CI."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .api import BASE_URL, CompaniesHouseClient, Response

SAMPLES = Path(__file__).parent / "tests" / "samples"
FILES = {"": "profile", "officers": "officers", "persons-with-significant-control": "psc"}


class FakeTransport:
    """Answers like Companies House from the sample files. `overrides` replaces a file's
    data for one path, so a test can change what the "service" says between syncs."""

    def __init__(self, samples: Path = SAMPLES):
        self.samples = samples
        self.overrides: dict[str, dict] = {}
        self.requests: list[str] = []

    def __call__(self, url: str, headers: dict) -> Response:
        self.requests.append(url)
        parsed = urlparse(url)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in self.overrides:
            return self._ok(self.overrides[path])
        if path == "/search/companies":
            text = query.get("q", [""])[0].lower()
            data = json.loads((self.samples / "search.json").read_text())
            data["items"] = [
                item
                for item in data["items"]
                if text in item["title"].lower() or text in item["company_number"].lower()
            ]
            data["total_results"] = len(data["items"])
            return self._ok(data)
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "company":
            folder = self.samples / parts[1]
            rest = "/".join(parts[2:])
            name = "filings" if rest == "filing-history" else FILES.get(rest)
            if name and (folder / f"{name}.json").is_file():
                return self._ok(json.loads((folder / f"{name}.json").read_text()))
        return Response(404, {}, b'{"errors":[{"error":"company-profile-not-found"}]}')

    @staticmethod
    def _ok(data: dict) -> Response:
        return Response(200, {"X-Ratelimit-Remain": "599"}, json.dumps(data).encode())

    def set(self, path: str, data: dict) -> None:
        self.overrides[path] = data

    def load(self, number: str, name: str) -> dict:
        return json.loads((self.samples / number / f"{name}.json").read_text())


# One transport for the process, so a test can adjust it through `fake_transport()`.
_transport = FakeTransport()


def fake_transport() -> FakeTransport:
    return _transport


def reset() -> None:
    _transport.overrides.clear()
    _transport.requests.clear()


def fake_client() -> CompaniesHouseClient:
    return CompaniesHouseClient(
        api_key="", transport=_transport, sleep=lambda seconds: None, min_interval=0
    )


__all__ = ["BASE_URL", "FakeTransport", "fake_client", "fake_transport", "reset"]
