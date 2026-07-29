import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from src.core.constants import TZ


class CardListing(Protocol):
    code: str
    name: str
    condition: str
    price: Decimal


def deduplicate_listings(listings: list["CardListing"]) -> list["CardListing"]:
    unique_by_identity: dict[tuple[str, str], CardListing] = {}

    for listing in listings:
        # Persistence identity is (source, code, condition). Transformation
        # handles one source at a time, so source is constant here. A repeated
        # row later in the page replaces an earlier generic row.
        key = (
            listing.code.strip().upper(),
            listing.condition.strip().casefold(),
        )
        unique_by_identity[key] = listing

    return list(unique_by_identity.values())


def sort_listings(listings: list["CardListing"]) -> list["CardListing"]:
    return sorted(
        listings,
        key=lambda x: (x.name.lower(), -extract_price_value(x.price)),
        reverse=True,  # ascending order
    )


def extract_price_value(price_str: str | Decimal) -> Decimal:
    if isinstance(price_str, Decimal):
        return price_str

    if price_str == "N/A":
        return Decimal(0)

    try:
        return Decimal(price_str.replace("$", "").replace(",", ""))
    except ValueError:
        return Decimal(0)


def to_slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s


def trim_card_name(card_name: str) -> str:
    left, _, _ = card_name.partition(" - ")
    return left


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "export"


def pluralize(noun: str) -> str:
    if re.search("[sxz]$", noun) or re.search("[^aeioudgkprt]h$", noun):
        return re.sub("$", "es", noun)

    if re.search("[^aeiou]y$", noun):
        return re.sub("y$", "ies", noun)

    return noun + "s"


def to_snake(camel: str) -> str:
    snake = re.sub(r"([a-zA-Z])([0-9])", lambda m: f"{m.group(1)}_{m.group(2)}", camel)
    snake = re.sub(r"([a-z0-9])([A-Z])", lambda m: f"{m.group(1)}_{m.group(2)}", snake)

    return snake.lower()


def datetime_now() -> datetime:
    return datetime.now(tz=TZ)


class Empty:
    def __str__(self) -> str:
        return "Empty"

    def __repr__(self) -> str:
        return "Empty"


class Undefined:
    def __str__(self) -> str:
        return "Undefined"

    def __repr__(self) -> str:
        return "Undefined"


EmptyType = Empty
UndefinedType = Undefined
