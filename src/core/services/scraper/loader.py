from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.repository.model import CardListing


@dataclass(slots=True)
class ScraperLoadResult:
    card_listings_loaded: int = 0


class ScraperDataStore(Protocol):
    async def upsert_card_listings(self, rows: Sequence[dict[str, object]]) -> int: ...


class CardListingData(Protocol):
    name: str
    set: str
    code: str
    price: str
    rarity: str
    condition: str
    stock: int


def _parse_price(price: str) -> Decimal:
    if price == "N/A":
        return Decimal(0)

    return Decimal(price.replace("$", "").replace(",", "").strip())


def _card_listing_row(listing: CardListingData) -> dict[str, object]:
    return {
        "name": listing.name,
        "ygo_set": listing.set,
        "code": listing.code,
        "price": _parse_price(listing.price),
        "rarity": listing.rarity,
        "condition": listing.condition,
        "stock": listing.stock,
    }


class SQLAlchemyScraperStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_card_listings(self, rows: Sequence[dict[str, object]]) -> int:
        if not rows:
            return 0

        stmt = postgresql_insert(CardListing).values(list(rows))
        stmt = stmt.on_conflict_do_update(
            constraint="uq_card_listings_code_condition",
            set_={
                "name": stmt.excluded.name,
                "ygo_set": stmt.excluded.ygo_set,
                "price": stmt.excluded.price,
                "rarity": stmt.excluded.rarity,
                "stock": stmt.excluded.stock,
            },
        )

        await self.db.execute(stmt)
        await self.db.commit()

        return len(rows)


async def load_scraped_data(
    store: ScraperDataStore,
    *,
    card_listings: Sequence[CardListingData] = (),
) -> ScraperLoadResult:
    card_rows = [_card_listing_row(listing) for listing in card_listings]

    card_listings_loaded = 0

    if card_rows:
        card_listings_loaded = await store.upsert_card_listings(card_rows)

    return ScraperLoadResult(card_listings_loaded=card_listings_loaded)


async def load_scraped_data_to_database(
    db: AsyncSession,
    *,
    card_listings: Sequence[CardListingData] = (),
) -> ScraperLoadResult:
    return await load_scraped_data(
        SQLAlchemyScraperStore(db), card_listings=card_listings
    )
