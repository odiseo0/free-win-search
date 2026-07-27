from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from enum import StrEnum
from time import monotonic
from urllib.parse import quote

import httpx

from src.core.constants import BASE_URL, USER_AGENT


class ExtractStatus(StrEnum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"


@dataclass(frozen=True, slots=True)
class ExtractResult:
    card_name: str
    status: ExtractStatus
    html: str | None = None
    status_code: int | None = None
    retry_after_seconds: int | None = None


def parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None

    try:
        return max(0, int(value))
    except ValueError:
        try:
            delta = parsedate_to_datetime(value).timestamp() - __import__("time").time()

            return max(0, int(delta))
        except (TypeError, ValueError, OverflowError):
            return None


class HostRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._interval - (monotonic() - self._last_request)

            if delay > 0:
                await asyncio.sleep(delay)

            self._last_request = monotonic()


async def fetch_card_page(
    client: httpx.AsyncClient,
    card_name: str,
    *,
    rate_limiter: HostRateLimiter | None = None,
) -> ExtractResult:
    encoded_name = quote(card_name, safe="").replace("%20", "+")

    if rate_limiter is not None:
        await rate_limiter.wait()

    try:
        response = await client.get(encoded_name)
    except httpx.TimeoutException:
        return ExtractResult(card_name, ExtractStatus.TIMEOUT)
    except httpx.RequestError:
        return ExtractResult(card_name, ExtractStatus.NETWORK_ERROR)

    if response.status_code == 404:
        return ExtractResult(
            card_name, ExtractStatus.NOT_FOUND, status_code=response.status_code
        )

    if response.status_code == 429:
        return ExtractResult(
            card_name,
            ExtractStatus.RATE_LIMITED,
            status_code=response.status_code,
            retry_after_seconds=parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.is_success:
        return ExtractResult(
            card_name, ExtractStatus.HTTP_ERROR, status_code=response.status_code
        )

    return ExtractResult(card_name, ExtractStatus.SUCCESS, html=response.text)


async def scrape_cards(
    cards: list[str],
    *,
    client: httpx.AsyncClient | None = None,
    concurrency: int = 5,
    timeout_seconds: float = 15.0,
    min_host_interval_seconds: float = 0.25,
) -> list[ExtractResult]:
    owns_client = client is None

    if client is None:
        client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    active_client = client
    semaphore = asyncio.Semaphore(concurrency)
    rate_limiter = HostRateLimiter(min_host_interval_seconds)

    async def fetch(card_name: str) -> ExtractResult:
        async with semaphore:
            return await fetch_card_page(
                active_client, card_name, rate_limiter=rate_limiter
            )

    try:
        return await asyncio.gather(*(fetch(card_name) for card_name in cards))
    finally:
        if owns_client:
            await active_client.aclose()
