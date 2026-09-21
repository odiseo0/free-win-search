from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from src.core.services.cache.memory import InMemoryCache
from src.core.services.scraper.transformers import ParserStructureError
from src.core.services.scraper.worker import ScrapeFlowError, ScraperWorker
from src.settings.scraper_settings import ScraperSettings


def _search_row(title: str, path: str, details: str = "") -> str:
    return f"""
    <div class="product-search-row main-container">
      <a class="productLink" href="{path}">
        <span itemprop="name">{title}</span>
      </a>
      <div class="breadcrumb-trail">YuGiOh » Promo</div>
      {details}
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


def _out_of_stock_product_page(title: str, code: str = "") -> str:
    return f"""
    <html><body>
      <h1 class="card-name">{title}</h1>
      <div class="products-container">
        <div class="row product-row">Notes: {code} Out of Stock</div>
      </div>
    </body></html>
    """


def _incomplete_product_page(title: str, code: str) -> str:
    return f"""
    <html><body>
      <h1 class="card-name">{title}</h1>
      <div class="products-container">
        <div class="row product-row">Notes: {code} Near Mint</div>
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


def test_search_flow_keeps_same_title_variants_and_accepts_out_of_stock() -> None:
    requested_paths: list[str] = []
    search_url = (
        "https://www.coolstuffinc.com/main_search.php?pa=searchOnName"
        "&page=1&resultsPerPage=25&q=Dark+Eradicator+Warlock"
    )
    products = {
        "/p/YuGiOh/DarkEradicatorPromo": _product_page(
            "Dark Eradicator Warlock", "25.99"
        ),
        "/p/YuGiOh/DarkEradicatorOTS": _incomplete_product_page(
            "Dark Eradicator Warlock", "OP02-EN006"
        ),
        "/p/YuGiOh/DarkEradicatorSD": _out_of_stock_product_page(
            "Dark Eradicator Warlock"
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)

        if request.url.path.endswith("/Dark+Eradicator+Warlock"):
            return httpx.Response(302, headers={"Location": search_url})

        if request.url.path == "/main_search.php":
            return httpx.Response(
                200,
                text=(
                    _search_row(
                        "Dark Eradicator Warlock",
                        "/p/YuGiOh/DarkEradicatorPromo",
                        "Notes: WCPP-EN014 1 Near Mint $25.99",
                    )
                    + _search_row(
                        "Dark Eradicator Warlock",
                        "/p/YuGiOh/DarkEradicatorOTS",
                        "Notes: OP02-EN006 Out of Stock",
                    )
                    + _search_row(
                        "Dark Eradicator Warlock",
                        "/p/YuGiOh/DarkEradicatorSD",
                        "Out of Stock",
                    )
                ),
            )

        if request.url.path in products:
            return httpx.Response(200, text=products[request.url.path])

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
            return await worker._extract_and_transform("Dark Eradicator Warlock")
        finally:
            await worker._client.aclose()
            executor.shutdown()

    result = asyncio.run(run())

    assert len(result.listings) == 1
    assert result.listings[0].stock == 2
    assert set(result.out_of_stock_codes) == {"OP02-EN006"}
    assert set(products).issubset(requested_paths)


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


def test_worker_records_specific_parser_error_code(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid4(),
        attempts=1,
        target=SimpleNamespace(
            canonical_name="Dark Eradicator Warlock",
            card_id=10,
            ygo_id=29436665,
        ),
    )
    recorded: dict[str, object] = {}

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    async def claim_next_job(*_: object, **__: object):
        return job

    class FailingWorker(ScraperWorker):
        async def _extract_and_transform(self, canonical_name: str):
            raise ParserStructureError(
                "listing_rows_missing_price",
                "Price missing",
                {"card_name": canonical_name, "rows_seen": 1},
            )

        async def _record_failure(
            self,
            failed_job,
            error_code: str,
            retry_override: int | None,
        ) -> None:
            recorded.update(
                job=failed_job,
                error_code=error_code,
                retry_override=retry_override,
            )

    monkeypatch.setattr(
        "src.core.services.scraper.worker.async_session_factory",
        SessionContext,
    )
    monkeypatch.setattr(
        "src.core.services.scraper.worker.claim_next_job",
        claim_next_job,
    )
    worker = FailingWorker(
        settings=ScraperSettings(min_host_interval_seconds=0),
        cache=InMemoryCache(),
    )

    processed = asyncio.run(worker.process_once())

    assert processed is True
    assert recorded["job"] is job
    assert recorded["error_code"] == "listing_rows_missing_price"
