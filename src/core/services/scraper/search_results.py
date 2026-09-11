from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.core.constants import BASE_URL


class SearchStructureError(ValueError):
    pass


class SearchPaginationError(SearchStructureError):
    pass


@dataclass(frozen=True, slots=True)
class SearchProduct:
    title: str
    url: str
    source_product_key: str


@dataclass(frozen=True, slots=True)
class SearchPage:
    products: tuple[SearchProduct, ...]
    next_url: str | None
    confirmed_empty: bool


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().strip('"').strip()
    return re.sub(r"\s+", " ", normalized).casefold()


def source_product_key(title: str) -> str:
    return normalize_search_text(title)


def _valid_product_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "www.coolstuffinc.com"
        and parsed.path.startswith("/p/YuGiOh/")
        and not parsed.query
        and not parsed.fragment
    )


def _validate_next_url(url: str, canonical_name: str, current_page: int) -> None:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    if parsed.scheme != "https" or parsed.netloc != "www.coolstuffinc.com":
        raise SearchPaginationError("Search pagination left CoolStuffInc")

    if parsed.path != "/main_search.php":
        raise SearchPaginationError("Search pagination path changed")

    if query.get("pa") != ["searchOnName"]:
        raise SearchPaginationError("Search pagination action changed")

    if normalize_search_text(query.get("q", [""])[0]) != normalize_search_text(
        canonical_name
    ):
        raise SearchPaginationError("Search pagination query changed")

    try:
        next_page = int(query.get("page", [""])[0])
    except ValueError as exc:
        raise SearchPaginationError("Search pagination page is invalid") from exc

    if next_page != current_page + 1:
        raise SearchPaginationError("Search pagination did not advance by one page")


def parse_search_page(
    html: str,
    *,
    canonical_name: str,
    current_url: str,
    current_page: int,
) -> SearchPage:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div.product-search-row.main-container")
    normalized_name = normalize_search_text(canonical_name)
    products: dict[str, SearchProduct] = {}

    for row in rows:
        title_node = row.select_one('[itemprop="name"]')
        link = row.select_one("a.productLink[href]")
        breadcrumb = row.select_one(".breadcrumb-trail")

        if title_node is None or link is None or breadcrumb is None:
            continue

        title = title_node.get_text(" ", strip=True)
        category = breadcrumb.get_text(" ", strip=True)
        url = urljoin(BASE_URL, str(link.get("href", "")))

        if normalized_name not in normalize_search_text(title):
            continue

        if not normalize_search_text(category).startswith("yugioh"):
            continue

        if not _valid_product_url(url):
            continue

        key = source_product_key(title)
        products[key] = SearchProduct(title=title, url=url, source_product_key=key)

    empty_text = "no results for items like" in normalize_search_text(
        soup.get_text(" ", strip=True)
    )

    if not rows and not empty_text:
        raise SearchStructureError("Unrecognized search result structure")

    next_urls = {
        urljoin(current_url, str(node.get("href", "")))
        for node in soup.select('link[rel="next"][href]')
    }

    if len(next_urls) > 1:
        raise SearchPaginationError("Search page has conflicting next links")

    next_url = next(iter(next_urls), None)

    if next_url is not None:
        _validate_next_url(next_url, canonical_name, current_page)

    return SearchPage(
        products=tuple(products.values()),
        next_url=next_url,
        confirmed_empty=empty_text,
    )
