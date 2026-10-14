"""Logs carry no tokens or personal data (spec 12 section 1, check 13)."""

import json
import logging

import pytest

from apps.core.logs import JsonFormatter, RedactFilter, redact


@pytest.mark.parametrize(
    "line, secret",
    [
        ("Forbidden (CSRF cookie not set.): /r/AbCdEf123456/", "AbCdEf123456"),
        ("Internal Server Error: /invite/tok-en_value/", "tok-en_value"),
        ("GET /sign/xyz789/pdf/ 200", "xyz789"),
        ("GET /proposal/p-token/ 404", "p-token"),
        ("GET /password/reset/key/zz-abc123/", "zz-abc123"),
        ("GET /integrations/xero/callback?code=SECRETCODE&state=STATE1", "SECRETCODE"),
    ],
)
def test_tokens_are_taken_out(line, secret):
    assert secret not in redact(line)
    assert "[redacted]" in redact(line)


def test_ordinary_addresses_are_left_alone():
    assert redact("GET /clients/12/ 200") == "GET /clients/12/ 200"


def test_the_filter_rewrites_formatted_messages():
    record = logging.LogRecord(
        "django.security.csrf",
        logging.WARNING,
        __file__,
        1,
        "Forbidden (%s): %s",
        ("CSRF cookie not set.", "/r/SECRET-TOKEN/"),
        None,
    )
    RedactFilter().filter(record)
    assert "SECRET-TOKEN" not in record.getMessage()


def test_a_csrf_failure_on_a_request_link_does_not_log_the_token(client, caplog):
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    with caplog.at_level(logging.INFO):
        strict.post("/r/PROBE-SECRET-TOKEN-0001/", {"x": "1"})
    handler_filter = RedactFilter()
    for record in caplog.records:
        handler_filter.filter(record)
        assert "PROBE-SECRET-TOKEN-0001" not in record.getMessage()


def test_the_console_handler_redacts():
    from django.conf import settings

    assert "redact" in settings.LOGGING["handlers"]["console"]["filters"]


def test_json_lines():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "GET /r/%s/", ("tok",), None)
    RedactFilter().filter(record)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["level"] == "INFO" and entry["message"] == "GET /r/[redacted]/"
