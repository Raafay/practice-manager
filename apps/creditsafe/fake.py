"""A stand-in for Creditsafe that serves made-up samples. For tests and demo data."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .api import Response

SAMPLES = Path(__file__).parent / "tests" / "samples"


class FakeCreditsafe:
    def __init__(self):
        self.requests = []
        self.reports = {}  # connect id -> sample dict, to change a rating between calls

    def _file(self, name):
        return json.loads((SAMPLES / f"{name}.json").read_text())

    def __call__(self, method, url, headers=None, body=None):
        parsed = urlparse(url)
        self.requests.append({"method": method, "path": parsed.path, "headers": headers or {}})
        path = parsed.path.removeprefix("/v1/")
        if path == "authenticate":
            return Response(200, json.dumps({"token": "made-up-token"}).encode())
        if path == "companies":
            number = parse_qs(parsed.query).get("regNo", [""])[0]
            data = self._file("search")
            if number == "00000404":
                data = {"companies": []}
            else:
                data["companies"][0]["id"] = f"GB-0-{number}"
            return Response(200, json.dumps(data).encode())
        if path.startswith("companies/"):
            connect_id = path.split("/", 1)[1]
            data = self.reports.get(connect_id) or self._file("report")
            data["report"]["companyId"] = connect_id
            return Response(200, json.dumps(data).encode())
        if path.startswith("monitoring/portfolios/"):
            return Response(201, b"{}")
        if path == "monitoring/notificationEvents":
            return Response(200, json.dumps(self._file("events")).encode())
        return Response(404, b"{}")
