import base64

import pytest

from apps.companieshouse import api
from apps.companieshouse.api import CompaniesHouseClient, Response
from apps.companieshouse.fake import fake_client


class Scripted:
    """A transport that answers from a list, and records what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []
        self.headers = []

    def __call__(self, url, headers):
        self.urls.append(url)
        self.headers.append(headers)
        return self.answers.pop(0)


def ok(body=b"{}"):
    return Response(200, {}, body)


def client_with(transport, key="test-key", now=1000.0):
    slept = []
    client = CompaniesHouseClient(
        api_key=key, transport=transport, sleep=slept.append, wall_clock=lambda: now
    )
    return client, slept


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234", "00001234"),
        ("09999901", "09999901"),
        (" 999 9901 ", "09999901"),
        ("sc1234", "SC001234"),
        ("NI012345", "NI012345"),
        ("OC999905", "OC999905"),
        ("R123", "R0000123"),
    ],
)
def test_company_numbers_are_padded_to_eight_characters(raw, expected):
    assert api.normalise_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "123456789", "ABC123", "12-34", "SC"])
def test_bad_company_numbers_are_refused(raw):
    with pytest.raises(api.InvalidNumber):
        api.normalise_number(raw)


def test_search_against_the_samples():
    items = fake_client().search("example")
    assert [i["company_number"] for i in items] == ["09999901"]
    assert items[0]["title"] == "EXAMPLE TRADING LTD"
    assert {"title", "company_number", "company_status", "address_snippet"} <= set(items[0])
    assert fake_client().search("   ") == []


def test_profile_against_the_samples():
    profile = fake_client().profile("9999901")
    assert profile["company_number"] == "09999901"
    assert profile["accounts"]["next_due"] == "2026-12-31"
    assert profile["confirmation_statement"]["next_due"] == "2026-11-03"


def test_officers_against_the_samples():
    officers = fake_client().officers("09999901")
    assert [o["officer_role"] for o in officers] == [
        "director",
        "secretary",
        "corporate-secretary",
    ]
    assert officers[0]["identity_verification_details"]["identity_verified_on"] == "2026-01-15"


def test_owners_against_the_samples():
    owners = fake_client().owners("08999903")
    assert len(owners) == 2
    assert owners[1]["ceased_on"] == "2025-06-30"


def test_filings_against_the_samples():
    filings = fake_client().filings("09999901")
    assert filings[0]["type"] == "CS01"
    assert filings[1]["description_values"]["made_up_date"] == "2025-03-31"


def test_an_unknown_company_is_not_found():
    with pytest.raises(api.NotFound):
        fake_client().profile("12345678")


def test_a_missing_owners_register_is_an_empty_list():
    transport = Scripted(Response(404, {}, b"{}"))
    client, _ = client_with(transport)
    assert client.owners("09999901") == []


def test_the_key_is_sent_as_basic_auth_with_an_empty_password():
    transport = Scripted(ok(b'{"company_number": "09999901"}'))
    client, _ = client_with(transport, key="made-up-key")
    client.profile("09999901")
    expected = base64.b64encode(b"made-up-key:").decode()
    assert transport.headers[0]["Authorization"] == f"Basic {expected}"
    assert "made-up-key" not in repr(client)


def test_a_429_waits_until_the_reset_time_and_retries():
    transport = Scripted(
        Response(429, {"X-Ratelimit-Reset": "1030", "X-Ratelimit-Remain": "0"}, b""),
        ok(b'{"company_number": "09999901"}'),
    )
    client, slept = client_with(transport, now=1000.0)
    assert client.profile("09999901")["company_number"] == "09999901"
    assert 30.0 in slept
    assert len(transport.urls) == 2


def test_repeated_429s_give_up():
    transport = Scripted(*[Response(429, {}, b"")] * 4)
    client, _ = client_with(transport)
    with pytest.raises(api.RateLimited):
        client.profile("09999901")


def test_a_5xx_is_retried_three_times_with_a_growing_wait():
    transport = Scripted(*[Response(502, {}, b"")] * 3, ok(b"{}"))
    client, slept = client_with(transport)
    client.profile("09999901")
    assert [s for s in slept if s >= 1] == [2, 4, 8]
    transport = Scripted(*[Response(503, {}, b"")] * 4)
    client, _ = client_with(transport)
    with pytest.raises(api.ServiceError):
        client.profile("09999901")


def test_a_401_is_reported_without_the_key():
    transport = Scripted(Response(401, {}, b""))
    client, _ = client_with(transport, key="secret-made-up")
    with pytest.raises(api.AuthFailed) as error:
        client.profile("09999901")
    assert "secret-made-up" not in str(error.value)
    assert "secret-made-up" not in error.value.public_message


def test_calls_are_paced_under_two_a_second():
    times = iter([0.0, 0.0, 0.1, 0.55])
    slept = []
    client = CompaniesHouseClient(
        api_key="k",
        transport=Scripted(ok(), ok()),
        sleep=slept.append,
        clock=lambda: next(times),
    )
    api._last_call[0] = -10
    client.profile("1")
    client.profile("2")
    assert slept and slept[0] == pytest.approx(0.45)


def test_a_long_list_is_read_page_by_page():
    first = b'{"items": [{"name": "A, B"}], "total_results": 2}'
    second = b'{"items": [{"name": "C, D"}], "total_results": 2}'
    transport = Scripted(ok(first), ok(second))
    client, _ = client_with(transport)
    assert len(client.officers("09999901")) == 2
    assert "start_index=1" in transport.urls[1]


def test_ch_check_prints_the_filing_dates(capsys):
    from django.core.management import call_command

    call_command("ch_check", "9999901")
    out = capsys.readouterr().out
    assert "EXAMPLE TRADING LTD" in out
    assert "Next accounts due:" in out and "31/12/2026" in out
    assert "Next statement due:" in out and "03/11/2026" in out


def test_ch_check_reports_an_unknown_company():
    from django.core.management import CommandError, call_command

    with pytest.raises(CommandError, match="no company with that number"):
        call_command("ch_check", "12345678")
