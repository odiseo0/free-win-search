from __future__ import annotations

import asyncio
import httpx
import pytest

from src.core.constants import BASE_URL
from src.core.services.scraper.scraper import (
    ExtractStatus,
    fetch_card_page,
    normalize_card_name,
    parse_retry_after,
)


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (200, ExtractStatus.SUCCESS),
        (404, ExtractStatus.NOT_FOUND),
        (429, ExtractStatus.RATE_LIMITED),
        (503, ExtractStatus.HTTP_ERROR),
    ],
)
def test_fetch_card_page_returns_typed_status(
    status_code: int,
    expected: ExtractStatus,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            text="<html></html>",
            headers={"Retry-After": "120"},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test/",
        ) as client:
            return await fetch_card_page(client, "Dark Magician")

    result = asyncio.run(run())

    assert result.status is expected
    assert result.retry_after_seconds == (120 if status_code == 429 else None)


def test_fetch_card_page_classifies_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow response", request=request)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.test/",
        ) as client:
            return await fetch_card_page(client, "Dark Magician")

    result = asyncio.run(run())

    assert result.status is ExtractStatus.TIMEOUT


def test_invalid_retry_after_is_ignored() -> None:
    assert parse_retry_after("not-a-delay") is None


def test_card_fetch_uses_only_the_direct_product_url() -> None:
    requested_urls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url)

        return httpx.Response(200, text="<html></html>")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=BASE_URL,
        ) as client:
            return await fetch_card_page(client, "Dark Magician")

    result = asyncio.run(run())

    assert result.status is ExtractStatus.SUCCESS
    assert requested_urls == [
        httpx.URL("https://www.coolstuffinc.com/p/YuGiOh/Dark+Magician")
    ]


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ('"Infernoble Arms - Durendal"', "Infernoble Arms - Durendal"),
        ('  "A Case for K9"  ', "A Case for K9"),
        ('Therion "King" Regulus', 'Therion "King" Regulus'),
    ],
)
def test_card_name_normalization_only_removes_boundary_quotes(
    raw_name: str,
    expected: str,
) -> None:
    assert normalize_card_name(raw_name) == expected


def test_fetch_removes_boundary_quotes_but_preserves_internal_quotes() -> None:
    requested_urls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url)

        return httpx.Response(200, text="<html></html>")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=BASE_URL,
        ) as client:
            outer = await fetch_card_page(client, '"Infernoble Arms - Durendal"')
            internal = await fetch_card_page(client, 'Therion "King" Regulus')

        return outer, internal

    outer, internal = asyncio.run(run())

    assert outer.card_name == "Infernoble Arms - Durendal"
    assert internal.card_name == 'Therion "King" Regulus'
    assert requested_urls == [
        httpx.URL(
            "https://www.coolstuffinc.com/p/YuGiOh/Infernoble+Arms+-+Durendal"
        ),
        httpx.URL(
            "https://www.coolstuffinc.com/p/YuGiOh/Therion+%22King%22+Regulus"
        ),
    ]
