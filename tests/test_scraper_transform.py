import pickle
from decimal import Decimal

import pytest

from src.core.services.scraper.transformers import (
    CardListing,
    ParserStructureError,
    parse_card_listings,
    transform_card_page,
)
from src.core.utils import deduplicate_listings


VALID_HTML = """
<html><body>
  <h1 class="card-name">Dark Magician</h1>
  <div class="products-container">
    <div class="row product-row">
      <a class="ItemSet display-title">Legend of Blue Eyes</a>
      Rarity: Ultra Rare Card # LOB-005 Near Mint Only 3 In Stock $12.50
    </div>
  </div>
</body></html>
"""


def test_transform_validates_decimal_and_metadata() -> None:
    result = transform_card_page(VALID_HTML, "Dark Magician")

    assert result.report.rows_valid == 1
    assert result.listings[0].price == Decimal("12.50")
    assert result.listings[0].stock == 3
    assert result.listings[0].condition == "Near Mint"


def test_text_fallback_uses_the_same_listing_detail_rules() -> None:
    html = """
    <html><body>
      <p>Rarity: Rare Card #: LOB-005 Played Only 2 In Stock $1.25</p>
    </body></html>
    """

    listings = parse_card_listings(html, "Dark Magician")

    assert len(listings) == 1
    assert listings[0].code == "LOB-005"
    assert listings[0].price == Decimal("1.25")
    assert listings[0].rarity == "Rare"
    assert listings[0].condition == "Played"
    assert listings[0].stock == 2


def test_text_fallback_accepts_notes_as_card_code_label() -> None:
    html = """
    <html><body>
      <p>Rarity: Rare Notes: WCPP-EN014 Near Mint Only 1 In Stock $25.99</p>
    </body></html>
    """

    listings = parse_card_listings(html, "Dark Eradicator Warlock")

    assert len(listings) == 1
    assert listings[0].code == "WCPP-EN014"
    assert listings[0].rarity == "Rare"


def test_transform_rejects_unrecognized_success_page() -> None:
    with pytest.raises(ParserStructureError) as raised:
        transform_card_page("<html><body>layout changed</body></html>", "Card")

    assert raised.value.code == "listing_page_unrecognized"


def test_transform_rejects_invalid_price_in_recognized_row() -> None:
    html = """
    <div class="products-container">
      <div class="row product-row">
        Card #: LOB-005 Near Mint In Stock Price unavailable
      </div>
    </div>
    """
    with pytest.raises(ParserStructureError) as raised:
        transform_card_page(html, "Dark Magician")

    assert raised.value.code == "listing_rows_missing_price"


def test_transform_accepts_explicit_out_of_stock_row_without_price() -> None:
    html = """
    <div class="products-container">
      <div class="row product-row">
        Notes: WCPP-EN014 Out of Stock
      </div>
    </div>
    """

    result = transform_card_page(html, "Dark Eradicator Warlock")

    assert result.listings == []
    assert result.out_of_stock_codes == ("WCPP-EN014",)
    assert result.report.rows_seen == 1
    assert result.report.rows_rejected == 1


@pytest.mark.parametrize(
    ("row_text", "expected_code"),
    [
        ("Near Mint $1.00", "listing_rows_missing_code"),
        ("LOB-005 $1.00", "listing_rows_missing_condition"),
    ],
)
def test_transform_reports_specific_invalid_row_reason(
    row_text: str,
    expected_code: str,
) -> None:
    html = f"""
    <div class="products-container">
      <div class="row product-row">{row_text}</div>
    </div>
    """

    with pytest.raises(ParserStructureError) as raised:
        transform_card_page(html, "Dark Magician")

    assert raised.value.code == expected_code


def test_parser_structure_error_keeps_diagnostics_across_processes() -> None:
    error = ParserStructureError(
        "listing_rows_missing_price",
        "Price missing",
        {"rows_seen": 1},
    )

    restored = pickle.loads(pickle.dumps(error))

    assert restored.code == "listing_rows_missing_price"
    assert str(restored) == "Price missing"
    assert restored.context == {"rows_seen": 1}


def test_transform_accepts_only_unequivocal_empty_page() -> None:
    result = transform_card_page(
        "<div class='products-container'>No products found</div>",
        "Card",
    )

    assert result.listings == []
    assert result.report.confirmed_empty is True


def test_deduplication_matches_database_identity_and_keeps_last_row() -> None:
    generic = CardListing(
        name="Cyber Dragon - Promo",
        set="Promo",
        code="YS18-EN014",
        price=Decimal("6.99"),
        rarity="Secret Rare",
        condition="Near Mint",
        stock=20,
    )
    specific = CardListing(
        name="Cyber Dragon - Starter Deck: Codebreaker",
        set="Starter Deck: Codebreaker",
        code="ys18-en014",
        price=Decimal("0.39"),
        rarity="Common",
        condition="Near Mint",
        stock=1,
    )

    assert deduplicate_listings([generic, specific]) == [specific]
