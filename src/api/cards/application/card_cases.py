from __future__ import annotations

from typing import TYPE_CHECKING, Never

from src.api.cards.domain import (
    CardCreate,
    CardListResponse,
    CardNotFound,
    CardResponse,
    CardUpdate,
)
from src.api.cards.repository import dao_cards as dao
from src.core import Err, Ok, Result
from src.core.services.cache import Cache
from src.core.utils.utils import Empty

from .cache import (
    get_cached_model,
    set_cached_model,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CARD_CACHE_PREFIX = "cards:"
CARD_CACHE_TTL_SECONDS = 300


def _card_key(card_id: int) -> str:
    return f"{CARD_CACHE_PREFIX}item:{card_id}"


async def get_one(
    db: AsyncSession,
    cache: Cache,
    card_id: int,
) -> Result[CardResponse, CardNotFound]:
    key = _card_key(card_id)
    cached = await get_cached_model(cache, key, CardResponse)

    if cached is not None:
        return Ok(cached)

    card = await dao.get(db, card_id)

    if card is Empty:
        return Err(CardNotFound(card_id))

    response = CardResponse.model_validate(card)
    await set_cached_model(
        cache,
        key,
        response,
        ttl_seconds=CARD_CACHE_TTL_SECONDS,
    )

    return Ok(response)


async def get_multi(
    db: AsyncSession,
    cache: Cache,
    *,
    page: int = 1,
    shows: int = 100,
) -> Result[CardListResponse, Never]:
    key = f"{CARD_CACHE_PREFIX}list:{page}:{shows}"
    cached = await get_cached_model(cache, key, CardListResponse)

    if cached is not None:
        return Ok(cached)

    cards, total = await dao.get_multi(
        db,
        page=(page - 1) * shows,
        shows=shows,
        ordering=[("name", False)],
    )
    response = CardListResponse(
        items=[CardResponse.model_validate(card) for card in cards],
        total=total,
    )
    await set_cached_model(
        cache,
        key,
        response,
        ttl_seconds=CARD_CACHE_TTL_SECONDS,
    )

    return Ok(response)


async def create(
    db: AsyncSession,
    cache: Cache,
    obj_in: CardCreate,
) -> Result[CardResponse, Never]:
    card = await dao.create(db, obj_in=obj_in)
    response = CardResponse.model_validate(card)

    await cache.delete_prefix(f"{CARD_CACHE_PREFIX}list:")
    await set_cached_model(
        cache,
        _card_key(response.id),
        response,
        ttl_seconds=CARD_CACHE_TTL_SECONDS,
    )

    return Ok(response)


async def update(
    db: AsyncSession,
    cache: Cache,
    card_id: int,
    obj_in: CardUpdate,
) -> Result[CardResponse, CardNotFound]:
    card = await dao.get(db, card_id)

    if card is Empty:
        return Err(CardNotFound(card_id))

    updated_card = await dao.update(db, card_id, obj_in)
    response = CardResponse.model_validate(updated_card)

    await cache.delete_prefix(f"{CARD_CACHE_PREFIX}list:")
    await set_cached_model(
        cache,
        _card_key(card_id),
        response,
        ttl_seconds=CARD_CACHE_TTL_SECONDS,
    )
    return Ok(response)


async def remove(
    db: AsyncSession,
    cache: Cache,
    card_id: int,
) -> Result[None, CardNotFound]:
    card = await dao.get(db, card_id)

    if card is Empty:
        return Err(CardNotFound(card_id))

    await dao.delete(db, db_object=card)
    await cache.delete(_card_key(card_id))
    await cache.delete_prefix(f"{CARD_CACHE_PREFIX}list:")

    return Ok(None)
