from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select

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

    async def search_text(
        self, db: AsyncSession, query: str, *, page: int, shows: int
    ) -> tuple[list[Card], int]:
        pattern = f"%{query.strip()}%"
        statement = select(self.model).where(
            or_(
                self.model.name.ilike(pattern),
                self.model.text.ilike(pattern),
            )
        )
        count = await self.count(db, statement)
        rows = (
            await db.execute(
                statement.order_by(self.model.name.asc(), self.model.id.asc())
                .offset((page - 1) * shows)
                .limit(shows)
            )
        ).scalars().all()
        return list(rows), count

    async def get_many_by_ids(
        self, db: AsyncSession, card_ids: list[int]
    ) -> list[Card]:
        if not card_ids:
            return []
        return list(
            (await db.execute(select(self.model).where(self.model.id.in_(card_ids))))
            .scalars()
            .all()
        )


class CardListingDAO(DAO[CardListing, CardListingResponse, CardListingResponse]):
    async def filtered(
        self,
        db: AsyncSession,
        *,
        page: int,
        shows: int,
        card_id: int | None = None,
        ygo_id: int | None = None,
        code: str | None = None,
        condition: str | None = None,
        rarity: str | None = None,
        source: str | None = None,
        is_active: bool = True,
        order_by: str = "price",
        descending: bool = False,
    ) -> tuple[list[CardListing], int]:
        statement = select(self.model).where(self.model.is_active.is_(is_active))
        values = {
            "card_id": card_id,
            "ygo_id": ygo_id,
            "condition": condition,
            "rarity": rarity,
            "source": source,
        }
        for field, value in values.items():
            if value is not None:
                statement = statement.where(getattr(self.model, field) == value)
        if code is not None:
            statement = statement.where(func.upper(self.model.code) == code.upper())
        ordering = getattr(self.model, order_by)
        statement = statement.order_by(
            ordering.desc() if descending else ordering.asc(), self.model.id.asc()
        )
        count = await self.count(db, statement)
        rows = (
            await db.execute(statement.offset((page - 1) * shows).limit(shows))
        ).scalars().all()
        return list(rows), count
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
