from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Never

from src.api.cards.domain import (
    CardListingListResponse,
    CardListingNotFound,
    CardListingResponse,
)
from src.api.cards.repository import dao_card_listings as dao
from src.core import Err, Ok, Result
from src.core.services.cache import Cache
from src.core.services.scraper import CardListingSearch
from src.core.services.scraper.transformers import CardListing as ScrapedCardListing
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


def _scraped_listing_response(listing: ScrapedCardListing) -> CardListingResponse:
    price: str | Decimal = listing.price

    if isinstance(price, str):
        price = Decimal(price.replace("$", "").replace(",", "").strip())

    return CardListingResponse(
        ygo_set=listing.set,
        name=listing.name,
        code=listing.code,
        price=price,
        rarity=listing.rarity,
        condition=listing.condition,
        stock=listing.stock,
    )


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
        cache,
        key,
        response,
        ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS,
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
        page=(page - 1) * shows,
        shows=shows,
        ordering=[("price", False)],
    )
    response = CardListingListResponse(
        items=[CardListingResponse.model_validate(listing) for listing in listings],
        total=total,
    )
    await set_cached_model(
        cache,
        key,
        response,
        ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS,
    )

    return Ok(response)


async def search(
    db: AsyncSession,
    cache: Cache,
    scraper: CardListingSearch,
    query: str,
    *,
    limit: int = 100,
) -> Result[list[CardListingResponse], Never]:
    key = _search_key(query, limit)
    cached = await get_cached_models(cache, key, CardListingResponse)

    if cached is not None:
        return Ok(cached)

    persisted = await dao.search_by_name(db, query, limit=limit)

    if persisted:
        response = [
            CardListingResponse.model_validate(listing) for listing in persisted
        ]
    else:
        scraped = await scraper.search(query)
        response = [_scraped_listing_response(listing) for listing in scraped]

    await set_cached_models(
        cache,
        key,
        response,
        ttl_seconds=CARD_LISTING_CACHE_TTL_SECONDS,
    )

    return Ok(response)
