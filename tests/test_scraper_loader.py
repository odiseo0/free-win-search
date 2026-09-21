import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.dialects import postgresql

from src.core.services.scraper.loader import (
    build_card_listing_rows,
    load_scraped_data_to_database,
)
from src.core.services.scraper.transformers import CardListing


def test_loader_never_emits_duplicate_postgresql_conflict_keys() -> None:
    observed_at = datetime(2026, 7, 27, tzinfo=UTC)
    first = CardListing(
        name="Dark Magician - Promo",
        set="Promo",
        code="BPT-001",
        price=Decimal("0.99"),
        rarity="Secret Rare",
        condition="Near Mint",
        stock=11,
        source_product_key="dark magician",
    )
    last = CardListing(
        name="Dark Magician - Promo",
        set="Promo",
        code="bpt-001",
        price=Decimal("4.99"),
        rarity="Secret Rare",
        condition="Near Mint",
        stock=2,
        source_product_key="dark magician",
    )

    rows = build_card_listing_rows(
        [first, last],
        card_id=2854,
        ygo_id=46986414,
        source="CoolStuffInc",
        observed_at=observed_at,
    )

    assert len(rows) == 1
    assert rows[0]["source"] == "coolstuffinc"
    assert rows[0]["code"] == "BPT-001"
    assert rows[0]["price"] == Decimal("4.99")


def test_loader_keeps_variants_with_the_same_code_and_condition() -> None:
    observed_at = datetime(2026, 7, 27, tzinfo=UTC)
    listings = [
        CardListing(
            name="Blue-Eyes White Dragon",
            set="Promo",
            code="LOB-001",
            price=Decimal("1.00"),
            rarity="Ultra Rare",
            condition="Near Mint",
            source_product_key="blue-eyes white dragon",
        ),
        CardListing(
            name="Blue-Eyes White Dragon (25th Anniversary Edition)",
            set="Promo",
            code="LOB-001",
            price=Decimal("2.00"),
            rarity="Ultra Rare",
            condition="Near Mint",
            source_product_key="blue-eyes white dragon (25th anniversary edition)",
        ),
    ]

    rows = build_card_listing_rows(
        listings,
        card_id=1,
        ygo_id=89631139,
        source="coolstuffinc",
        observed_at=observed_at,
    )

    assert len(rows) == 2


class _RowCountResult:
    rowcount = 1


class _RecordingDB:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _RowCountResult:
        self.statements.append(statement)

        return _RowCountResult()


def test_loader_zeroes_only_existing_listings_with_observed_codes() -> None:
    db = _RecordingDB()
    observed_at = datetime(2026, 9, 21, tzinfo=UTC)

    result = asyncio.run(
        load_scraped_data_to_database(
            db,  # type: ignore[arg-type]
            card_id=10,
            ygo_id=29436665,
            out_of_stock_codes=("wcpp-en014",),
            observed_at=observed_at,
        )
    )

    assert result.card_listings_zeroed == 1
    assert len(db.statements) == 1
    compiled = db.statements[0].compile(dialect=postgresql.dialect())  # type: ignore[union-attr]
    sql = str(compiled)

    assert "UPDATE card_listings" in sql
    assert "card_listings.card_id" in sql
    assert "card_listings.code IN" in sql
    assert ["WCPP-EN014"] in compiled.params.values()
    assert ["SD6-EN001"] not in compiled.params.values()


def test_loader_does_not_zero_a_code_seen_in_stock() -> None:
    db = _RecordingDB()
    observed_at = datetime(2026, 9, 21, tzinfo=UTC)
    listing = CardListing(
        name="Dark Eradicator Warlock",
        set="Promo",
        code="WCPP-EN014",
        price=Decimal("25.99"),
        rarity="Rare",
        condition="Near Mint",
        stock=1,
        source_product_key="dark eradicator warlock",
    )

    result = asyncio.run(
        load_scraped_data_to_database(
            db,  # type: ignore[arg-type]
            card_id=10,
            ygo_id=29436665,
            card_listings=(listing,),
            out_of_stock_codes=("WCPP-EN014",),
            observed_at=observed_at,
        )
    )

    assert result.card_listings_loaded == 1
    assert result.card_listings_zeroed == 0
    assert len(db.statements) == 1


def test_loader_ignores_unidentifiable_out_of_stock_product() -> None:
    db = _RecordingDB()

    result = asyncio.run(
        load_scraped_data_to_database(
            db,  # type: ignore[arg-type]
            card_id=10,
            ygo_id=29436665,
            out_of_stock_codes=(),
        )
    )

    assert result.card_listings_zeroed == 0
    assert db.statements == []
