from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.repository.model import CardListing


@dataclass(frozen=True, slots=True)
class ScraperLoadResult:
    card_listings_loaded: int = 0
    card_listings_deactivated: int = 0


class CardListingData(Protocol):
    name: str
    set: str
    code: str
    price: Decimal
    rarity: str
    condition: str
    stock: int


def _card_listing_row(
    listing: CardListingData,
    *,
    card_id: int,
    ygo_id: int,
    source: str,
    observed_at: datetime,
) -> dict[str, object]:
    if not listing.code.strip() or not listing.condition.strip():
        raise ValueError("Listing code and condition are required")
    if listing.price < 0 or listing.stock < 0:
        raise ValueError("Listing price and stock cannot be negative")
    return {
        "card_id": card_id,
        "ygo_id": ygo_id,
        "source": source.strip().casefold(),
        "name": listing.name,
        "ygo_set": listing.set,
        "code": listing.code.strip().upper(),
        "price": listing.price,
        "rarity": listing.rarity,
        "condition": listing.condition.strip(),
        "currency": "USD",
        "stock": listing.stock,
        "last_seen_at": observed_at,
        "is_active": True,
        "date_updated": observed_at,
    }


def build_card_listing_rows(
    card_listings: Sequence[CardListingData],
    *,
    card_id: int,
    ygo_id: int,
    source: str,
    observed_at: datetime,
) -> list[dict[str, object]]:
    unique_rows: dict[tuple[str, str, str], dict[str, object]] = {}

    for listing in card_listings:
        row = _card_listing_row(
            listing,
            card_id=card_id,
            ygo_id=ygo_id,
            source=source,
            observed_at=observed_at,
        )
        identity = (
            str(row["source"]).casefold(),
            str(row["code"]).upper(),
            str(row["condition"]).casefold(),
        )
        # Defense in depth: PostgreSQL cannot update the same conflict key
        # twice within one INSERT. Keep the last observation deterministically.
        unique_rows[identity] = row

    return list(unique_rows.values())


async def load_scraped_data_to_database(
    db: AsyncSession,
    *,
    card_id: int,
    ygo_id: int,
    card_listings: Sequence[CardListingData] = (),
    source: str = "coolstuffinc",
    confirmed_empty: bool = False,
    observed_at: datetime | None = None,
) -> ScraperLoadResult:
    seen_at = observed_at or datetime.now(UTC)
    rows = build_card_listing_rows(
        card_listings,
        card_id=card_id,
        ygo_id=ygo_id,
        source=source,
        observed_at=seen_at,
    )

    if rows:
        stmt = postgresql_insert(CardListing).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_card_listings_source_code_condition",
            set_={
                "card_id": stmt.excluded.card_id,
                "ygo_id": stmt.excluded.ygo_id,
                "name": stmt.excluded.name,
                "ygo_set": stmt.excluded.ygo_set,
                "price": stmt.excluded.price,
                "rarity": stmt.excluded.rarity,
                "currency": stmt.excluded.currency,
                "stock": stmt.excluded.stock,
                "last_seen_at": stmt.excluded.last_seen_at,
                "is_active": True,
                "date_updated": stmt.excluded.date_updated,
            },
        )
        await db.execute(stmt)

    deactivated = 0

    if confirmed_empty:
        result = await db.execute(
            update(CardListing)
            .where(
                CardListing.card_id == card_id,
                CardListing.source == source.strip().casefold(),
                CardListing.is_active.is_(True),
            )
            .values(is_active=False, date_updated=seen_at)
        )
        deactivated = result.rowcount  # type: ignore[attr-defined]

    return ScraperLoadResult(len(rows), deactivated)
