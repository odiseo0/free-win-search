from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Never
from uuid import UUID

from sqlalchemy import select

from src.api.cards.domain import (
    CardListingListResponse,
    CardListingNotFound,
    CardListingResponse,
    ScrapeAcceptedResponse,
    ScrapeJobNotFound,
    ScrapeJobResponse,
    ScrapeJobStatus,
)
from src.api.cards.repository import dao_card_listings as dao
from src.api.cards.repository import dao_cards
from src.api.cards.repository.model import ScrapeTarget
from src.api.cards.repository.scrape_jobs import enqueue_for_card, get_job
from src.core import Err, Ok, Result
from src.core.services.cache import Cache
from src.core.utils.utils import Empty

from .cache import (
    get_cached_model,
    get_cached_models,
    set_cached_model,
    set_cached_models,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CARD_LISTING_CACHE_PREFIX = "card-listings:"
CARD_LISTING_CACHE_TTL_SECONDS = 300


def _listing_key(card_listing_id: int) -> str:
    return f"{CARD_LISTING_CACHE_PREFIX}item:{card_listing_id}"


def _search_key(query: str, limit: int) -> str:
    normalized_query = " ".join(query.strip().casefold().split())

    return f"{CARD_LISTING_CACHE_PREFIX}search:{normalized_query}:{limit}"


async def get_one(
    db: AsyncSession,
    cache: Cache,
    card_listing_id: int,
) -> Result[CardListingResponse, CardListingNotFound]:
    key = _listing_key(card_listing_id)
    cached = await get_cached_model(cache, key, CardListingResponse)

    if cached is not None:
        return Ok(cached)

    listing = await dao.get(db, card_listing_id)

    if listing is Empty:
        return Err(CardListingNotFound(card_listing_id))

    response = CardListingResponse.model_validate(listing)
    await set_cached_model(
        cache, key, response, ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS
    )

    return Ok(response)


async def get_multi(
    db: AsyncSession,
    cache: Cache,
    *,
    page: int = 1,
    shows: int = 100,
) -> Result[CardListingListResponse, Never]:
    key = f"{CARD_LISTING_CACHE_PREFIX}list:{page}:{shows}"
    cached = await get_cached_model(cache, key, CardListingListResponse)

    if cached is not None:
        return Ok(cached)

    listings, total = await dao.get_multi(
        db,
        where={"is_active": True},
        page=(page - 1) * shows,
        shows=shows,
        ordering=[("price", False)],
    )
    response = CardListingListResponse(
        items=[CardListingResponse.model_validate(item) for item in listings],
        total=total,
    )
    await set_cached_model(
        cache, key, response, ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS
    )

    return Ok(response)


async def search(
    db: AsyncSession,
    cache: Cache,
    query: str,
    *,
    limit: int = 100,
) -> Result[list[CardListingResponse] | ScrapeAcceptedResponse, Never]:
    key = _search_key(query, limit)
    cached = await get_cached_models(cache, key, CardListingResponse)

    if cached is not None:
        return Ok(cached)

    card = await dao_cards.resolve_canonical(db, query)
    persisted = (
        await dao.for_card(db, card_id=card.id, limit=limit)
        if card is not None
        else await dao.search_by_name(db, query, limit=limit)
    )
    response = [CardListingResponse.model_validate(item) for item in persisted]

    # Non-canonical or ambiguous input may read existing rows but cannot enqueue.
    if card is None:
        await set_cached_models(
            cache, key, response, ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS
        )

        return Ok(response)

    target = (
        await db.execute(select(ScrapeTarget).where(ScrapeTarget.card_id == card.id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    unavailable = target is not None and not target.is_enabled
    fresh = (
        target is not None
        and target.next_refresh_at is not None
        and target.next_refresh_at > now
    )

    if unavailable or fresh:
        await set_cached_models(
            cache, key, response, ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS
        )

        return Ok(response)

    job = await enqueue_for_card(db, card, now=now)

    if job is None:
        return Ok(response)

    if response:
        return Ok(response)

    return Ok(
        ScrapeAcceptedResponse(
            job_id=job.id,
            ygo_id=card.ygo_id,
            status=ScrapeJobStatus(job.status),
            status_url=f"/card-listings/jobs/{job.id}",
            retry_after_seconds=2,
        )
    )


async def get_scrape_job(
    db: AsyncSession,
    job_id: UUID,
) -> Result[ScrapeJobResponse, ScrapeJobNotFound]:
    job = await get_job(db, job_id)

    if job is None:
        return Err(ScrapeJobNotFound(job_id))

    return Ok(
        ScrapeJobResponse(
            job_id=job.id,
            ygo_id=job.target.ygo_id,
            status=ScrapeJobStatus(job.status),
            attempts=job.attempts,
            available_at=job.available_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            error_code=job.error_code,
        )
    )
