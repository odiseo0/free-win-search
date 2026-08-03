from typing import Protocol

from .scraper import ExtractStatus, scrape_cards
from .transformers import CardListing, transform_card_page


class CardListingSearch(Protocol):
    async def search(self, query: str) -> list[CardListing]: ...


class ScraperCardListingSearch:
    async def search(self, query: str) -> list[CardListing]:
        extraction = (await scrape_cards([query]))[0]

        if extraction.status is not ExtractStatus.SUCCESS or extraction.html is None:
            return []

        return transform_card_page(extraction.html, extraction.card_name).listings


_card_listing_search: CardListingSearch = ScraperCardListingSearch()


def get_card_listing_search() -> CardListingSearch:
    return _card_listing_search
