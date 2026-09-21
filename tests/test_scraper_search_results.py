from __future__ import annotations

import pytest

from src.core.services.scraper.search_results import (
    SearchStructureError,
    parse_search_page,
)


def _page(*rows: str, next_links: str = "") -> str:
    return f"<html><head>{next_links}</head><body>{''.join(rows)}</body></html>"


def _row(title: str, href: str, category: str = "YuGiOh » Promo") -> str:
    return f"""
    <div class="product-search-row main-container">
      <a class="productLink" href="{href}">
        <span itemprop="name">{title}</span>
      </a>
      <div class="breadcrumb-trail">{category}</div>
    </div>
    """


def test_search_parser_keeps_yugioh_variants_and_rejects_other_results() -> None:
    html = _page(
        _row("Blue-Eyes White Dragon", "/p/YuGiOh/BlueEyesWhiteDragon"),
        _row(
            "Blue-Eyes White Dragon (25th Anniversary Edition)",
            "/p/YuGiOh/BlueEyesWhiteDragon25th",
        ),
        _row("Blue-Eyes Toon Dragon", "/p/YuGiOh/BlueEyesToonDragon"),
        _row(
            "Blue-Eyes White Dragon Dial",
            "/p/HeroClix/BlueEyesWhiteDragon",
            "HeroClix » Yu-Gi-Oh",
        ),
    )

    page = parse_search_page(
        html,
        canonical_name="Blue-Eyes White Dragon",
        current_url=(
            "https://www.coolstuffinc.com/main_search.php?pa=searchOnName"
            "&page=1&resultsPerPage=25&q=Blue-Eyes+White+Dragon"
        ),
        current_page=1,
    )

    assert [product.title for product in page.products] == [
        "Blue-Eyes White Dragon",
        "Blue-Eyes White Dragon (25th Anniversary Edition)",
    ]


def test_search_parser_keeps_same_title_variants_by_url() -> None:
    html = _page(
        _row("Dark Eradicator Warlock", "/p/YuGiOh/DarkEradicatorPromo"),
        _row("Dark Eradicator Warlock", "/p/YuGiOh/DarkEradicatorOTS"),
        """
        <div class="product-search-row main-container">
          <a class="productLink" href="/p/YuGiOh/DarkEradicatorSD">
            <span itemprop="name">Dark Eradicator Warlock</span>
          </a>
          <div class="breadcrumb-trail">YuGiOh » Structure Deck</div>
          <span>Out of Stock</span>
          <span>Notes: WCPP-EN014</span>
        </div>
        """,
    )

    page = parse_search_page(
        html,
        canonical_name="Dark Eradicator Warlock",
        current_url="https://www.coolstuffinc.com/main_search.php",
        current_page=1,
    )

    assert len(page.products) == 3
    assert {product.url for product in page.products} == {
        "https://www.coolstuffinc.com/p/YuGiOh/DarkEradicatorPromo",
        "https://www.coolstuffinc.com/p/YuGiOh/DarkEradicatorOTS",
        "https://www.coolstuffinc.com/p/YuGiOh/DarkEradicatorSD",
    }
    assert {product.source_product_key for product in page.products} == {
        "dark eradicator warlock"
    }
    assert page.products[-1].out_of_stock is True
    assert page.products[-1].observed_code == "WCPP-EN014"


def test_search_parser_accepts_duplicate_identical_next_links() -> None:
    next_url = (
        "/main_search.php?pa=searchOnName&page=2&resultsPerPage=25"
        "&q=Blue-Eyes+White+Dragon"
    )
    html = _page(
        _row("Blue-Eyes White Dragon", "/p/YuGiOh/BlueEyesWhiteDragon"),
        next_links=(
            f'<link rel="next" href="{next_url}">'
            f'<link rel="next" href="{next_url}">'
        ),
    )

    page = parse_search_page(
        html,
        canonical_name="Blue-Eyes White Dragon",
        current_url="https://www.coolstuffinc.com/main_search.php",
        current_page=1,
    )

    assert page.next_url is not None
    assert "page=2" in page.next_url


def test_search_parser_rejects_query_change_in_pagination() -> None:
    html = _page(
        _row("Cyber Dragon", "/p/YuGiOh/CyberDragon"),
        next_links=(
            '<link rel="next" href="/main_search.php?pa=searchOnName&page=2'
            '&q=Dark+Magician">'
        ),
    )

    with pytest.raises(SearchStructureError):
        parse_search_page(
            html,
            canonical_name="Cyber Dragon",
            current_url="https://www.coolstuffinc.com/main_search.php",
            current_page=1,
        )


def test_search_parser_only_confirms_known_empty_message() -> None:
    page = parse_search_page(
        "<html><body>No results for items like asfasfsdg</body></html>",
        canonical_name="asfasfsdg",
        current_url="https://www.coolstuffinc.com/main_search.php",
        current_page=1,
    )

    assert page.confirmed_empty is True
    assert page.products == ()

    with pytest.raises(SearchStructureError):
        parse_search_page(
            "<html><body>layout changed</body></html>",
            canonical_name="asfasfsdg",
            current_url="https://www.coolstuffinc.com/main_search.php",
            current_page=1,
        )
