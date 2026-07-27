from decimal import Decimal

import pytest

from src.core.services.scraper.transformers import (
    ParserStructureError,
    transform_card_page,
)


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


def test_transform_rejects_unrecognized_success_page() -> None:
    with pytest.raises(ParserStructureError):
        transform_card_page("<html><body>layout changed</body></html>", "Card")


def test_transform_rejects_invalid_price_in_recognized_row() -> None:
    html = """
    <div class="products-container">
      <div class="row product-row">
        Card #: LOB-005 Near Mint In Stock Price unavailable
      </div>
    </div>
    """
    with pytest.raises(ParserStructureError):
        transform_card_page(html, "Dark Magician")


def test_transform_accepts_only_unequivocal_empty_page() -> None:
    result = transform_card_page(
        "<div class='products-container'>No products found</div>",
        "Card",
    )

    assert result.listings == []
    assert result.report.confirmed_empty is True
