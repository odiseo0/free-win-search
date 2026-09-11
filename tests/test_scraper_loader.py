from datetime import UTC, datetime
from decimal import Decimal

from src.core.services.scraper.loader import build_card_listing_rows
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
