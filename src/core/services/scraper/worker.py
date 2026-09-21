from __future__ import annotations

import asyncio
import json
import logging
import random
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from time import monotonic
from typing import Self

from httpx import URL, AsyncClient

from src.api.cards.repository.model import ScrapeJob
from src.api.cards.repository.scrape_jobs import (
    backlog_size,
    claim_next_job,
    mark_job_failed,
    mark_job_succeeded,
)
from src.core.db.deps import async_session_factory
from src.core.services.cache import Cache, get_cache
from src.settings.scraper_settings import ScraperSettings, scraper_settings

from .loader import load_scraped_data_to_database
from .policy import next_refresh_at
from .scraper import (
    ExtractStatus,
    PageKind,
    classify_coolstuff_url,
    create_http_client,
    fetch_card_page,
    fetch_url,
)
from .search_results import (
    SearchPaginationError,
    SearchProduct,
    SearchStructureError,
    normalize_search_text,
    parse_search_page,
    source_product_key,
)
from .transformers import (
    ParserStructureError,
    TransformReport,
    TransformResult,
    extract_product_page_name,
    transform_card_page,
)

logger = logging.getLogger("free_win.scraper_worker")


def _log(event: str, **context: object) -> None:
    logger.info(json.dumps({"event": event, **context}, default=str))


class ScrapeFlowError(RuntimeError):
    def __init__(self, code: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class ScraperWorker:
    def __init__(
        self,
        *,
        settings: ScraperSettings = scraper_settings,
        cache: Cache | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or get_cache()
        self._client: AsyncClient | None = None
        self._executor: ProcessPoolExecutor | None = None
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        self._client = create_http_client(
            timeout_seconds=self.settings.http_timeout_seconds,
            cookies=self.settings.cookies,
        )
        self._executor = ProcessPoolExecutor()
        await self.cache.start()

        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()

        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)

        await self.cache.close()

    async def _wait_for_host(self) -> None:
        async with self._rate_lock:
            delay = self.settings.min_host_interval_seconds - (
                monotonic() - self._last_request_at
            )

            if delay > 0:
                await asyncio.sleep(delay)

            self._last_request_at = monotonic()

    async def process_once(self) -> bool:
        async with async_session_factory() as db:
            job = await claim_next_job(db, lease_seconds=self.settings.lease_seconds)

        if job is None:
            return False

        started = monotonic()
        error_code: str | None = None
        retry_override: int | None = None

        try:
            transformed = await asyncio.wait_for(
                self._extract_and_transform(job.target.canonical_name),
                timeout=self.settings.job_timeout_seconds,
            )
            now = datetime.now(UTC)

            async with async_session_factory() as db:
                in_stock_count = sum(
                    1 for listing in transformed.listings if listing.stock > 0
                )
                await load_scraped_data_to_database(
                    db,
                    card_id=job.target.card_id,
                    ygo_id=job.target.ygo_id,
                    card_listings=transformed.listings,
                    out_of_stock_codes=transformed.out_of_stock_codes,
                    confirmed_empty=transformed.report.confirmed_empty,
                    observed_at=now,
                )
                await mark_job_succeeded(
                    db,
                    job.id,
                    result_count=len(transformed.listings),
                    in_stock_count=in_stock_count,
                    next_refresh_at=next_refresh_at(now, in_stock_count=in_stock_count),
                    now=now,
                )
                await db.commit()

            try:
                await self.cache.delete_prefix("card-listings:")
            except Exception:
                logger.exception(
                    "cache invalidation failed after successful commit",
                    extra={"job_id": str(job.id)},
                )

            _log(
                "job_succeeded",
                job_id=job.id,
                ygo_id=job.target.ygo_id,
                attempt=job.attempts,
                duration_seconds=round(monotonic() - started, 3),
                result_count=len(transformed.listings),
                in_stock_count=in_stock_count,
            )

            return True
        except TimeoutError:
            error_code = "job_timeout"
        except SearchPaginationError:
            error_code = "search_pagination"
        except SearchStructureError:
            error_code = "search_structure"
        except ParserStructureError as exc:
            error_code = exc.code
            _log(
                "parser_rejected",
                job_id=job.id,
                ygo_id=job.target.ygo_id,
                error_code=exc.code,
                message=str(exc),
                **exc.context,
            )
        except ScrapeFlowError as exc:
            error_code = exc.code
            retry_override = exc.retry_after_seconds
        except Exception:
            error_code = "internal_error"
            logger.exception("unexpected scraper job failure")

        await self._record_failure(job, error_code or "unknown", retry_override)
        _log(
            "job_failed",
            job_id=job.id,
            ygo_id=job.target.ygo_id,
            attempt=job.attempts,
            duration_seconds=round(monotonic() - started, 3),
            error_code=error_code,
        )

        return True

    async def _request_url(self, url: str):
        await self._wait_for_host()
        assert self._client is not None
        result = await fetch_url(self._client, url)

        if result.status is not ExtractStatus.SUCCESS:
            raise ScrapeFlowError(result.status.value, result.retry_after_seconds)

        if result.html is None or result.final_url is None:
            raise ScrapeFlowError("empty_response")

        return result

    async def _extract_and_transform(self, canonical_name: str) -> TransformResult:
        await self._wait_for_host()
        assert self._client is not None
        initial = await fetch_card_page(self._client, canonical_name)

        if initial.status is not ExtractStatus.SUCCESS:
            raise ScrapeFlowError(initial.status.value, initial.retry_after_seconds)

        if initial.html is None or initial.final_url is None:
            raise ScrapeFlowError("empty_response")

        initial_url = URL(initial.final_url)
        kind = classify_coolstuff_url(initial_url, canonical_name)

        if kind is PageKind.PRODUCT:
            return await self._transform_product(
                initial.html,
                canonical_name,
                source_product_key(canonical_name),
            )

        if kind is not PageKind.SEARCH_RESULTS:
            raise ScrapeFlowError("unexpected_page")

        products: dict[str, SearchProduct] = {}
        seen_pages: set[str] = set()
        current_html = initial.html
        current_url = initial.final_url
        page_number = 1
        confirmed_empty = False

        while True:
            if current_url in seen_pages:
                raise ScrapeFlowError("search_pagination")

            seen_pages.add(current_url)
            page = parse_search_page(
                current_html,
                canonical_name=canonical_name,
                current_url=current_url,
                current_page=page_number,
            )
            confirmed_empty = confirmed_empty or page.confirmed_empty

            for product in page.products:
                products[product.url] = product

            if page.next_url is None:
                break

            if page_number >= self.settings.max_search_pages:
                raise ScrapeFlowError("search_page_limit")

            next_result = await self._request_url(page.next_url)

            if URL(next_result.final_url or "") != URL(page.next_url):
                raise ScrapeFlowError("search_pagination")

            current_html = next_result.html or ""
            current_url = next_result.final_url or ""
            page_number += 1

        if not products:
            if confirmed_empty:
                return TransformResult(
                    [], TransformReport(0, 0, 0, confirmed_empty=True)
                )

            raise ScrapeFlowError("search_structure")

        transformed_pages: list[TransformResult] = []

        for product in products.values():
            result = await self._request_url(product.url)

            if URL(result.final_url or "") != URL(product.url):
                raise ScrapeFlowError("product_redirect")

            page_title = extract_product_page_name(result.html or "")

            if page_title is None or normalize_search_text(
                canonical_name
            ) not in normalize_search_text(page_title):
                raise ScrapeFlowError("product_redirect")

            try:
                transformed = await self._transform_product(
                    result.html or "",
                    product.title,
                    product.source_product_key,
                )
            except ParserStructureError as exc:
                exc.context = {**exc.context, "product_url": product.url}

                if not (product.out_of_stock and exc.code.startswith("listing_rows_")):
                    raise

                observed_codes = (
                    (product.observed_code,) if product.observed_code else ()
                )
                _log(
                    "out_of_stock_product_incomplete",
                    product_url=product.url,
                    product_title=product.title,
                    observed_code=product.observed_code,
                    parser_error_code=exc.code,
                )
                transformed = TransformResult(
                    [],
                    TransformReport(
                        rows_seen=int(exc.context.get("rows_seen", 0)),
                        rows_valid=0,
                        rows_rejected=int(exc.context.get("rows_seen", 0)),
                    ),
                    out_of_stock_codes=observed_codes,
                )

            if product.out_of_stock and product.observed_code:
                transformed = TransformResult(
                    transformed.listings,
                    transformed.report,
                    out_of_stock_codes=tuple(
                        dict.fromkeys(
                            (*transformed.out_of_stock_codes, product.observed_code)
                        )
                    ),
                )

            if (
                product.out_of_stock
                and product.observed_code is None
                and not transformed.out_of_stock_codes
            ):
                _log(
                    "out_of_stock_product_unidentifiable",
                    product_url=product.url,
                    product_title=product.title,
                )

            transformed_pages.append(transformed)

        listings = [
            listing
            for transformed in transformed_pages
            for listing in transformed.listings
        ]
        rows_seen = sum(item.report.rows_seen for item in transformed_pages)
        out_of_stock_codes = tuple(
            dict.fromkeys(
                code
                for transformed in transformed_pages
                for code in transformed.out_of_stock_codes
            )
        )

        return TransformResult(
            listings=listings,
            report=TransformReport(
                rows_seen=rows_seen,
                rows_valid=len(listings),
                rows_rejected=sum(
                    item.report.rows_rejected for item in transformed_pages
                ),
            ),
            out_of_stock_codes=out_of_stock_codes,
        )

    async def _transform_product(
        self, html: str, title: str, product_key: str
    ) -> TransformResult:
        loop = asyncio.get_running_loop()
        assert self._executor is not None

        return await loop.run_in_executor(
            self._executor,
            transform_card_page,
            html,
            title,
            product_key,
        )

    async def _record_failure(
        self,
        job: ScrapeJob,
        error_code: str,
        retry_override: int | None,
    ) -> None:
        delay_index = min(
            max(job.attempts - 1, 0),
            len(self.settings.retry_delays_seconds) - 1,
        )
        configured = self.settings.retry_delays_seconds[delay_index]
        base_delay = retry_override if retry_override is not None else configured
        jittered_delay = max(1, round(base_delay * random.uniform(0.9, 1.1)))

        async with async_session_factory() as db:
            await mark_job_failed(
                db,
                job.id,
                error_code=error_code,
                max_attempts=self.settings.max_attempts,
                retry_delay_seconds=jittered_delay,
                terminal=error_code == ExtractStatus.NOT_FOUND.value,
                disable_target=error_code == ExtractStatus.NOT_FOUND.value,
            )

    async def run_forever(self) -> None:
        _log(
            "worker_started",
            poll_seconds=self.settings.poll_seconds,
            cookie_count=len(self.settings.cookies),
            cookie_names=[cookie.name for cookie in self.settings.cookies],
        )

        while True:
            processed = await asyncio.gather(
                *(self.process_once() for _ in range(self.settings.concurrency))
            )

            if not any(processed):
                async with async_session_factory() as db:
                    backlog = await backlog_size(db)

                _log("worker_heartbeat", backlog=backlog)
                await asyncio.sleep(self.settings.poll_seconds)


async def run_once() -> bool:
    async with ScraperWorker() as worker:
        return await worker.process_once()


async def run_worker() -> None:
    async with ScraperWorker() as worker:
        await worker.run_forever()
