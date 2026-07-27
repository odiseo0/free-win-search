from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from src.api.cards.domain import CardCreate, CardListingResponse, CardUpdate
from src.core.db import DAO

from .model import Card, CardListing

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class CardDAO(DAO[Card, CardCreate, CardUpdate]):
    async def resolve_canonical(self, db: AsyncSession, query: str) -> Card | None:
        normalized = " ".join(query.strip().casefold().split())
        statement = (
            select(self.model).where(func.lower(self.model.name) == normalized).limit(2)
        )
        matches = list((await db.execute(statement)).scalars().all())

        return matches[0] if len(matches) == 1 else None


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
            .where(
                func.lower(self.model.name).contains(normalized_query),
                self.model.is_active.is_(True),
            )
            .order_by(self.model.price.asc(), self.model.code.asc())
            .limit(limit)
        )

        return list((await db.execute(statement)).unique().scalars().all())

    async def for_card(
        self,
        db: AsyncSession,
        *,
        card_id: int,
        limit: int = 100,
    ) -> list[CardListing]:
        statement = (
            select(self.model)
            .where(
                self.model.card_id == card_id,
                self.model.is_active.is_(True),
            )
            .order_by(self.model.price.asc(), self.model.code.asc())
            .limit(limit)
        )

        return list((await db.execute(statement)).unique().scalars().all())


dao_cards = CardDAO(Card)
dao_card_listings = CardListingDAO(CardListing)
