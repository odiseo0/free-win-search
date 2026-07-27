import asyncio
import os
import re
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from bs4 import BeautifulSoup

from src.core.utils import deduplicate_listings

# make the parse executor reusable to the whole app.
_PARSE_EXECUTOR: ProcessPoolExecutor | None = None
PARSE_MAX_WORKERS = max(1, os.process_cpu_count() or 1)


@dataclass
class CardListing:
    name: str
    set: str
    code: str
    price: str
    rarity: str
    condition: str
    stock: int = 0


@dataclass
class CollectionItem:
    name: str
    set: str
    code: str
    qty: int
    price: str
    rarity: str
    condition: str
    stock: int

    @property
    def key(self) -> str:
        return f"{self.code}:{self.condition}"


def _get_parse_executor() -> ProcessPoolExecutor:
    global _PARSE_EXECUTOR

    if _PARSE_EXECUTOR is None:
        _PARSE_EXECUTOR = ProcessPoolExecutor(max_workers=PARSE_MAX_WORKERS)

    return _PARSE_EXECUTOR


def _parse_card_listing_task(card_and_html: tuple[str, str]) -> list[CardListing]:
    card_name, html = card_and_html
    return parse_card_listings(html, card_name)


def parse_listings_from_text(soup: BeautifulSoup, card_name: str) -> list[CardListing]:
    listings: list[CardListing] = []
    full_text = soup.get_text()

    code_pattern = re.compile(r"Card #:\s*([A-Z]{2,4}\d*-(?:[A-Z]{2,3})?\d+)")
    codes = code_pattern.findall(full_text)

    for code in codes:
        code_pos = full_text.find("Card #:" + code)

        if code_pos == -1:
            code_pos = full_text.find(code)

        if code_pos == -1:
            continue

        start = max(0, code_pos - 500)
        end = min(len(full_text), code_pos + 300)
        section = full_text[start:end]

        rarity = "Unknown"
        rarity_match = re.search(r"Rarity:\s*([A-Za-z\s]+?)(?:Card #|$)", section)

        if rarity_match:
            rarity = rarity_match.group(1).strip()

        price = "N/A"
        price_match = re.search(r"\$(\d+\.?\d*)", section[section.find(code) :])

        if price_match:
            price = f"${price_match.group(1)}"

        stock = 0
        stock_match = re.search(
            r"(?:Only\s+)?(\d+)\s+In Stock", section[section.find(code) :]
        )

        if stock_match:
            stock = int(stock_match.group(1))

        condition = "Unknown"
        condition_section = section[section.find(code) :]

        if "Near Mint" in condition_section[:100]:
            condition = "Near Mint"
        elif "Played" in condition_section[:100]:
            condition = "Played"

        if code and price != "N/A":
            listings.append(
                CardListing(
                    name=card_name,
                    set="",
                    code=code,
                    price=price,
                    rarity=rarity,
                    condition=condition,
                    stock=stock,
                )
            )

    return listings


def extract_listing_from_row(row, card_name: str) -> CardListing | None:
    row_text = row.get_text()

    if "$" not in row_text:
        return None

    code_pattern = re.compile(r"[A-Z]{2,4}\d*-(?:[A-Z]{2,3})?\d+")
    code_match = code_pattern.search(row_text)

    if not code_match:
        return None

    code = code_match.group(0)

    rarity = "Unknown"
    rarity_match = re.search(
        r"Rarity:\s*([A-Za-z\s]+?)(?:\s*Card #|\s*\(|\s*Only|\s*In Stock|\s*Out)",
        row_text,
    )

    if rarity_match:
        rarity = rarity_match.group(1).strip()

    condition = "Unknown"

    if "Near Mint" in row_text:
        condition = "Near Mint"
    elif "Played" in row_text:
        condition = "Played"

    stock = 0
    stock_match = re.search(r"(?:Only\s+)?(\d+)\s+In Stock", row_text)

    if stock_match:
        stock = int(stock_match.group(1))

    price = "N/A"
    price_match = re.search(r"\$\s*(\d+\.?\d*)", row_text)

    if price_match:
        price = f"${price_match.group(1)}"

    set_name = ""
    set_link = row.select_one("a.ItemSet.display-title")

    if set_link is not None:
        set_name = set_link.get_text(strip=True)

    return CardListing(
        name=f"{card_name} - {set_name}",
        set=set_name,
        code=code,
        price=price,
        rarity=rarity,
        condition=condition,
        stock=stock,
    )


def parse_card_listings(html: str, card_name: str) -> list[CardListing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[CardListing] = []

    page_card_name = extract_page_card_name(soup, card_name)
    product_rows = soup.select("div.products-container div.row")

    if not product_rows:
        product_rows = soup.select("div.row.product-row")

    if not product_rows:
        product_rows = soup.find_all("div", class_="row")

    for row in product_rows:
        try:
            listing = extract_listing_from_row(row, page_card_name)

            if listing:
                listings.append(listing)
        except Exception:
            continue

    if not listings:
        listings = parse_listings_from_text(soup, page_card_name)

    return deduplicate_listings(listings)


async def transform_card_pages(
    scraped_pages: Iterable[tuple[str, str | None]],
) -> list[CardListing]:
    parse_inputs = [(card_name, html) for card_name, html in scraped_pages if html]

    if not parse_inputs:
        return []

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(
            _get_parse_executor(), _parse_card_listing_task, parse_input
        )
        for parse_input in parse_inputs
    ]
    parsed_lists = await asyncio.gather(*tasks)

    listings: list[CardListing] = []

    for parsed in parsed_lists:
        listings.extend(parsed)

    return listings


def extract_page_card_name(soup: BeautifulSoup, default_name: str) -> str:
    header = soup.find("h1", class_="card-name")

    if header is None:
        return default_name

    page_name = header.get_text(strip=True)

    if not page_name:
        return default_name

    return page_name
