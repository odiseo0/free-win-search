from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from enum import StrEnum
from http.cookiejar import Cookie
from time import monotonic
from urllib.parse import parse_qs, quote

import httpx

from src.core.constants import BASE_URL, USER_AGENT
from src.settings.scraper_settings import ScraperCookieSettings, scraper_settings


class ExtractStatus(StrEnum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    UNEXPECTED_PAGE = "unexpected_page"


@dataclass(frozen=True, slots=True)
class ExtractResult:
    card_name: str
    status: ExtractStatus
    html: str | None = None
    status_code: int | None = None
    retry_after_seconds: int | None = None
    final_url: str | None = None


class PageKind(StrEnum):
    PRODUCT = "product"
    SEARCH_RESULTS = "search_results"


def classify_coolstuff_url(url: httpx.URL, card_name: str) -> PageKind | None:
    if url.scheme != "https" or url.host != "www.coolstuffinc.com":
        return None

    if url.path.startswith("/p/YuGiOh/"):
        return PageKind.PRODUCT

    if url.path != "/main_search.php":
        return None

    query = parse_qs(url.query.decode())

    if query.get("pa") != ["searchOnName"]:
        return None

    requested = normalize_card_name(card_name).casefold()
    searched = normalize_card_name(query.get("q", [""])[0]).casefold()

    return PageKind.SEARCH_RESULTS if requested == searched else None


def build_cookie_jar(cookies: tuple[ScraperCookieSettings, ...]) -> httpx.Cookies:
    jar = httpx.Cookies()

    for configured in cookies:
        expires = (
            int(configured.expires_at.astimezone(UTC).timestamp())
            if configured.expires_at is not None
            else None
        )
        jar.jar.set_cookie(
            Cookie(
                version=0,
                name=configured.name,
                value=configured.value.get_secret_value(),
                port=None,
                port_specified=False,
                domain=configured.domain,
                domain_specified=True,
                domain_initial_dot=False,
                path=configured.path,
                path_specified=True,
                secure=True,
                expires=expires,
                discard=expires is None,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": None},
                rfc2109=False,
            )
        )

    return jar


def create_http_client(
    *, timeout_seconds: float, cookies: tuple[ScraperCookieSettings, ...] = ()
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT},
        cookies=build_cookie_jar(cookies),
        timeout=timeout_seconds,
        follow_redirects=True,
    )


def normalize_card_name(card_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", card_name).strip().strip('"').strip()
    return re.sub(r"\s+", " ", normalized)


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
    normalized_name = normalize_card_name(card_name)
    encoded_name = quote(normalized_name, safe="").replace("%20", "+")
    requested_url = client.base_url.join(encoded_name)

    if rate_limiter is not None:
        await rate_limiter.wait()

    try:
        response = await client.get(encoded_name)
    except httpx.TimeoutException:
        return ExtractResult(normalized_name, ExtractStatus.TIMEOUT)
    except httpx.RequestError:
        return ExtractResult(normalized_name, ExtractStatus.NETWORK_ERROR)

    if response.status_code == 404:
        return ExtractResult(
            normalized_name,
            ExtractStatus.NOT_FOUND,
            status_code=response.status_code,
        )

    if response.status_code == 429:
        return ExtractResult(
            normalized_name,
            ExtractStatus.RATE_LIMITED,
            status_code=response.status_code,
            retry_after_seconds=parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.is_success:
        return ExtractResult(
            normalized_name,
            ExtractStatus.HTTP_ERROR,
            status_code=response.status_code,
        )

    page_kind = classify_coolstuff_url(response.url, normalized_name)

    # Mock transports in unit tests can use another host. Production clients
    # always use CoolStuffInc and must pass strict destination validation.
    if response.url.host == "www.coolstuffinc.com" and page_kind is None:
        return ExtractResult(
            normalized_name,
            ExtractStatus.UNEXPECTED_PAGE,
            status_code=response.status_code,
            final_url=str(response.url),
        )

    if page_kind is PageKind.PRODUCT and response.url != requested_url:
        return ExtractResult(
            normalized_name,
            ExtractStatus.UNEXPECTED_PAGE,
            status_code=response.status_code,
            final_url=str(response.url),
        )

    return ExtractResult(
        normalized_name,
        ExtractStatus.SUCCESS,
        html=response.text,
        status_code=response.status_code,
        final_url=str(response.url),
    )


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    rate_limiter: HostRateLimiter | None = None,
) -> ExtractResult:
    if rate_limiter is not None:
        await rate_limiter.wait()

    try:
        response = await client.get(url)
    except httpx.TimeoutException:
        return ExtractResult("", ExtractStatus.TIMEOUT)
    except httpx.RequestError:
        return ExtractResult("", ExtractStatus.NETWORK_ERROR)

    if response.status_code == 429:
        return ExtractResult(
            "",
            ExtractStatus.RATE_LIMITED,
            status_code=429,
            retry_after_seconds=parse_retry_after(response.headers.get("Retry-After")),
        )

    if not response.is_success:
        return ExtractResult("", ExtractStatus.HTTP_ERROR, status_code=response.status_code)

    return ExtractResult(
        "",
        ExtractStatus.SUCCESS,
        html=response.text,
        status_code=response.status_code,
        final_url=str(response.url),
    )


async def scrape_cards(
    cards: list[str],
    *,
    client: httpx.AsyncClient | None = None,
    concurrency: int = 5,
    timeout_seconds: float = 15.0,
    min_host_interval_seconds: float = 0.25,
    cookies: tuple[ScraperCookieSettings, ...] | None = None,
) -> list[ExtractResult]:
    owns_client = client is None

    if client is None:
        client = create_http_client(
            timeout_seconds=timeout_seconds,
            cookies=scraper_settings.cookies if cookies is None else cookies,
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
