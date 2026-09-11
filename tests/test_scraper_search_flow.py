from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import httpx
import pytest

from src.core.services.cache.memory import InMemoryCache
from src.core.services.scraper.worker import ScrapeFlowError, ScraperWorker
from src.settings.scraper_settings import ScraperSettings


def _search_row(title: str, path: str) -> str:
    return f"""
    <div class="product-search-row main-container">
      <a class="productLink" href="{path}">
        <span itemprop="name">{title}</span>
      </a>
      <div class="breadcrumb-trail">YuGiOh » Promo</div>
    </div>
    """


def _product_page(title: str, price: str) -> str:
    return f"""
    <html><body>
      <h1 class="card-name">{title}</h1>
      <div class="products-container">
        <div class="row product-row">
          <a class="ItemSet display-title">Promo</a>
          Rarity: Ultra Rare Card # LOB-001 Near Mint Only 2 In Stock ${price}
        </div>
      </div>
    </body></html>
    """


def test_search_flow_follows_pages_and_fetches_each_variant() -> None:
    requested_paths: list[str] = []
    search_url = (
        "https://www.coolstuffinc.com/main_search.php?pa=searchOnName"
        "&page=1&resultsPerPage=25&q=Blue-Eyes+White+Dragon"
    )
    page_two = (
        "/main_search.php?pa=searchOnName&page=2&resultsPerPage=25"
        "&q=Blue-Eyes+White+Dragon"
    )
    base_product = "/p/YuGiOh/BlueEyesWhiteDragon"
    variant_product = "/p/YuGiOh/BlueEyesWhiteDragon25th"

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)

        if request.url.path.endswith("/Blue-Eyes+White+Dragon"):
            return httpx.Response(302, headers={"Location": search_url})

        if request.url.path == "/main_search.php" and request.url.params["page"] == "1":
            return httpx.Response(
                200,
                text=(
                    _search_row("Blue-Eyes White Dragon", base_product)
                    + f'<link rel="next" href="{page_two.replace("&", "&amp;")}">'
                ),
            )

        if request.url.path == "/main_search.php":
            return httpx.Response(
                200,
                text=_search_row(
                    "Blue-Eyes White Dragon (25th Anniversary Edition)",
                    variant_product,
                ),
            )

        if request.url.path == base_product:
            return httpx.Response(200, text=_product_page("Blue-Eyes White Dragon", "1.00"))

        if request.url.path == variant_product:
            return httpx.Response(
                200,
                text=_product_page(
                    "Blue-Eyes White Dragon (25th Anniversary Edition)", "2.00"
                ),
            )

        raise AssertionError(f"Unexpected request: {request.url}")

    async def run():
        worker = ScraperWorker(
            settings=ScraperSettings(min_host_interval_seconds=0),
            cache=InMemoryCache(),
        )
        worker._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://www.coolstuffinc.com/p/YuGiOh/",
            follow_redirects=True,
        )
        executor = ThreadPoolExecutor(max_workers=1)
        worker._executor = cast(Any, executor)

        try:
            return await worker._extract_and_transform("Blue-Eyes White Dragon")
        finally:
            await worker._client.aclose()
            executor.shutdown()

    result = asyncio.run(run())

    assert len(result.listings) == 2
    assert {listing.source_product_key for listing in result.listings} == {
        "blue-eyes white dragon",
        "blue-eyes white dragon (25th anniversary edition)",
    }
    assert requested_paths.count("/main_search.php") == 2


def test_search_flow_fails_before_fetching_products_at_page_limit() -> None:
    search_url = (
        "https://www.coolstuffinc.com/main_search.php?pa=searchOnName"
        "&page=1&q=Cyber+Dragon"
    )
    product_requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal product_requested

        if request.url.path.endswith("/Cyber+Dragon"):
            return httpx.Response(302, headers={"Location": search_url})

        if request.url.path.startswith("/p/YuGiOh/"):
            product_requested = True

        return httpx.Response(
            200,
            text=(
                _search_row("Cyber Dragon", "/p/YuGiOh/CyberDragon")
                + '<link rel="next" href="/main_search.php?pa=searchOnName'
                '&amp;page=2&amp;q=Cyber+Dragon">'
            ),
        )

    async def run() -> None:
        worker = ScraperWorker(
            settings=ScraperSettings(
                min_host_interval_seconds=0,
                max_search_pages=1,
            ),
            cache=InMemoryCache(),
        )
        worker._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://www.coolstuffinc.com/p/YuGiOh/",
            follow_redirects=True,
        )
        executor = ThreadPoolExecutor(max_workers=1)
        worker._executor = cast(Any, executor)

        try:
            with pytest.raises(ScrapeFlowError, match="search_page_limit"):
                await worker._extract_and_transform("Cyber Dragon")
        finally:
            await worker._client.aclose()
            executor.shutdown()

    asyncio.run(run())
    assert product_requested is False
