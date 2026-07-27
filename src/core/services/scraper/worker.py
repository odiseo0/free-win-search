from __future__ import annotations

import asyncio
import json
import logging
import random
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from time import monotonic
from typing import Self

import httpx

from src.api.cards.repository.model import ScrapeJob
from src.api.cards.repository.scrape_jobs import (
    backlog_size,
    claim_next_job,
    mark_job_failed,
    mark_job_succeeded,
)
from src.core.constants import BASE_URL, USER_AGENT
from src.core.db.deps import async_session_factory
from src.core.services.cache import Cache, get_cache
from src.settings.scraper_settings import ScraperSettings, scraper_settings

from .loader import load_scraped_data_to_database
from .policy import next_refresh_at
from .scraper import ExtractStatus, fetch_card_page
from .transformers import ParserStructureError, TransformResult, transform_card_page

logger = logging.getLogger("free_win.scraper_worker")


def _log(event: str, **context: object) -> None:
    logger.info(json.dumps({"event": event, **context}, default=str))


class ScraperWorker:
    def __init__(
        self,
        *,
        settings: ScraperSettings = scraper_settings,
        cache: Cache | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or get_cache()
        self._client: httpx.AsyncClient | None = None
        self._executor: ProcessPoolExecutor | None = None
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
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
            await self._wait_for_host()
            assert self._client is not None
            extraction = await fetch_card_page(self._client, job.target.canonical_name)

            if extraction.status is not ExtractStatus.SUCCESS:
                error_code = extraction.status.value
                retry_override = extraction.retry_after_seconds

                raise RuntimeError(error_code)

            if extraction.html is None:
                error_code = "empty_response"

                raise RuntimeError(error_code)

            loop = asyncio.get_running_loop()

            assert self._executor is not None

            transformed: TransformResult = await loop.run_in_executor(
                self._executor,
                transform_card_page,
                extraction.html,
                job.target.canonical_name,
            )
            now = datetime.now(UTC)

            async with async_session_factory() as db:
                await load_scraped_data_to_database(
                    db,
                    card_id=job.target.card_id,
                    ygo_id=job.target.ygo_id,
                    card_listings=transformed.listings,
                    confirmed_empty=transformed.report.confirmed_empty,
                    observed_at=now,
                )
                await mark_job_succeeded(
                    db,
                    job.id,
                    result_count=len(transformed.listings),
                    next_refresh_at=next_refresh_at(job.target.last_requested_at, now),
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
            )

            return True
        except ParserStructureError:
            error_code = "parser_structure"
        except RuntimeError:
            pass
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
            )

    async def run_forever(self) -> None:
        _log("worker_started", poll_seconds=self.settings.poll_seconds)

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
