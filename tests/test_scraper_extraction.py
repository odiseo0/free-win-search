from __future__ import annotations

import asyncio
import httpx
import pytest

from src.core.services.scraper.scraper import (
    ExtractStatus,
    fetch_card_page,
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
