from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.api.cards.domain import CardCreate, CardListingResponse, CardUpdate
from src.core.db import DAO

from .model import Card, CardListing

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CardDAO(DAO[Card, CardCreate, CardUpdate]):
    pass


class CardListingDAO(DAO[CardListing, CardListingResponse, CardListingResponse]):
    async def search_by_name(
        self,
        db: AsyncSession,
        query: str,
        *,
        limit: int = 100,
    ) -> list[CardListing]:
        normalized_query = query.strip().lower()
        statement = (
            select(self.model)
            .where(func.lower(self.model.name).contains(normalized_query))
            .order_by(self.model.price.asc(), self.model.code.asc())
            .limit(limit)
        )

        return list((await db.execute(statement)).unique().scalars().all())


dao_cards = CardDAO(Card)
dao_card_listings = CardListingDAO(CardListing)
