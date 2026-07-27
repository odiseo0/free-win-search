from typing import Protocol

from .scraper import scrape_cards
from .transformers import CardListing, transform_card_pages


class CardListingSearch(Protocol):
    async def search(self, query: str) -> list[CardListing]: ...


class ScraperCardListingSearch:
    async def search(self, query: str) -> list[CardListing]:
        pages = await scrape_cards([query])
        return await transform_card_pages(pages)


_card_listing_search: CardListingSearch = ScraperCardListingSearch()


def get_card_listing_search() -> CardListingSearch:
    return _card_listing_search
