import asyncio
from collections.abc import Iterable
from urllib.parse import quote

from httpx import AsyncClient, HTTPStatusError, RequestError

from src.core.constants import BASE_URL, REQUEST_TIMEOUT_SECONDS, USER_AGENT

# optimized for batch processing and heavy loads
MAX_SCRAPE_CONCURRENCY = 50


async def scrape_cards(cards: list[str]) -> Iterable[tuple[str, str | None]]:
    semaphore = asyncio.Semaphore(MAX_SCRAPE_CONCURRENCY)
    tasks: list[asyncio.Task] = []

    async def _bounded_fetch(client, url: str) -> str | None:
        async with semaphore:
            return await fetch_card_page(client, url)

    async with AsyncClient(
        base_url=BASE_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        for card_name in cards:
            encoded_name = quote(card_name, safe="").replace("%20", "+")
            tasks.append(asyncio.create_task(_bounded_fetch(client, encoded_name)))

        htmls = await asyncio.gather(*tasks)

    return zip(cards, htmls)


async def fetch_card_page(client: AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url)
        response.raise_for_status()

        return response.text
    except HTTPStatusError as error:
        if error.response.status_code == 404:
            return None

        return None
    except RequestError:
        return None
