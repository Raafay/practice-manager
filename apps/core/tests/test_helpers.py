from decimal import Decimal

import pytest
from django.test import RequestFactory

from apps.core import ratelimit
from apps.core.money import format_money
from apps.core.pagination import page_query, paginate


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("1234.5"), "£1,234.50"),
        (Decimal("0"), "£0.00"),
        (Decimal("-12.345"), "-£12.35"),
        (1000000, "£1,000,000.00"),
        (None, ""),
    ],
)
def test_format_money(value, text):
    assert format_money(value) == text


def test_format_money_without_pence():
    assert format_money(Decimal("1234.50"), pence=False) == "£1,235"


def test_rate_limit_allows_up_to_the_limit_then_refuses():
    key = "test:203.0.113.1"
    assert all(ratelimit.hit(key, 3, 60) for _ in range(3))
    assert ratelimit.hit(key, 3, 60) is False
    assert ratelimit.is_limited(key, 3)
    ratelimit.reset(key)
    assert ratelimit.hit(key, 3, 60) is True


def test_rate_limit_keys_are_separate():
    assert ratelimit.hit("token:a", 1, 60)
    assert ratelimit.hit("token:b", 1, 60)
    assert not ratelimit.hit("token:a", 1, 60)


def test_paginate_and_page_query():
    request = RequestFactory().get("/list/", {"page": "2", "verb": "auth.signed_in"})
    page = paginate(request, list(range(120)), per_page=50)
    assert page.number == 2
    assert list(page.object_list)[0] == 50
    assert page_query(request, 3) == "page=3&verb=auth.signed_in"


def test_paginate_bad_page_gives_nearest():
    request = RequestFactory().get("/list/", {"page": "999"})
    assert paginate(request, list(range(10)), per_page=5).number == 2
