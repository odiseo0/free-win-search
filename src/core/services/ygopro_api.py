from typing import TypedDict

from httpx import AsyncClient, HTTPStatusError, RequestError

from src.core.constants import REQUEST_TIMEOUT_SECONDS, YGO_API_URL


class YGOPROCardImage(TypedDict):
    id: int
    image_url: str
    image_url_small: str
    image_url_cropped: str


class YGOPROCard(TypedDict):
    id: int
    name: str
    type: str
    frameType: str
    card_images: list[dict]


class YGROPROResponse(TypedDict):
    data: list[YGOPROCard]
    error: str | None


async def fuzzy_search(query: str) -> list[YGROPROResponse]:
    normalized_query = query.strip().lower()

    if not normalized_query:
        return []

    async with AsyncClient(
        base_url=YGO_API_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(url=YGO_API_URL, params={"fname": normalized_query})
        response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("YGOPRO devolvió una respuesta inesperada")

    return [payload]


async def get_card_by_id(id: int) -> YGROPROResponse:
    async with AsyncClient(
        base_url=YGO_API_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        response = await client.get(url=YGO_API_URL, params={"id": id})
        response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("YGOPRO devolvió una respuesta inesperada")

    return payload


async def safe_get_card_by_id(id: int) -> YGROPROResponse | None:
    try:
        return await get_card_by_id(id)
    except (HTTPStatusError, RequestError, ValueError):
        return None


async def get_cards_by_ids(ids: list[int]) -> list[YGOPROCard]:
    if not ids:
        return []

    joined_ids = ",".join(str(id) for id in ids)

    async with AsyncClient(
        base_url=YGO_API_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as client:
        try:
            response = await client.get(f"{YGO_API_URL}?id={joined_ids}")
            response.raise_for_status()
        except (HTTPStatusError, RequestError) as _:
            return []

    try:
        payload = response.json()
    except ValueError:
        return []

    data = payload.get("data")

    if not isinstance(data, list):
        return []

    cards: list[YGOPROCard] = []

    for entry in data:
        if isinstance(entry, dict):
            cards.append(entry)

    return cards
