import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.cards.application.search import MeilisearchCardSearch
from src.api.cards.application.search_deps import get_card_search
from src.api.cards.application.search_documents import card_to_search_document
from src.api.cards.domain import CardCreate, CardSearchDocument
from src.application import app
from src.core import Ok
from src.core.services.meilisearch import SearchResult, TaskInfo, TaskStatus
from src.core.db import get_db


TORNADO = {
    "ygo_id": 6983839,
    "name": "Tornado Dragon",
    "card_type": "XYZ Monster",
    "race": "Wyrm",
    "text": "2 Level 4 monsters",
    "attribute": "WIND",
    "sets": [
        {
            "set_name": "Battles of Legend: Relentless Revenge",
            "set_code": "BLRR-EN084",
            "set_rarity": "Secret Rare",
            "set_rarity_code": "(ScR)",
            "set_price": "4.08",
        }
    ],
    "images": [
        {
            "id": 6983839,
            "image_url": "https://images.ygoprodeck.com/images/cards/6983839.jpg",
            "image_url_small": "https://images.ygoprodeck.com/images/cards_small/6983839.jpg",
            "image_url_cropped": "https://images.ygoprodeck.com/images/cards_cropped/6983839.jpg",
        }
    ],
    "prices": [{"cardmarket_price": "0.42", "tcgplayer_price": "0.48"}],
}


def test_card_contract_validates_ygopro_arrays_and_decimal() -> None:
    card = CardCreate.model_validate(TORNADO)
    assert card.sets[0].set_price == Decimal("4.08")
    assert card.prices[0].cardmarket_price == Decimal("0.42")
    assert card.images[0].image_url_small.endswith("6983839.jpg")


@pytest.mark.parametrize("field", ["sets", "images", "prices"])
def test_card_contract_rejects_legacy_objects(field: str) -> None:
    payload = {**TORNADO, field: {}}
    with pytest.raises(ValueError):
        CardCreate.model_validate(payload)


def test_search_document_mapper_excludes_prices() -> None:
    now = datetime.now(UTC)
    card = SimpleNamespace(
        id=7,
        date_added=now,
        date_updated=None,
        **TORNADO,
    )
    document = card_to_search_document(card)
    payload = document.model_dump(mode="json")
    assert payload["card_id"] == 7
    assert payload["source_updated_at"] == now.isoformat().replace("+00:00", "Z")
    assert payload["document_version"] == 1
    assert "prices" not in payload
    assert "short_name" not in payload


class FakeClient:
    def __init__(self) -> None:
        self.added = None
        self.closed = False

    async def search(self, index_uid, query):
        del index_uid, query
        return SearchResult(hits=[])

    async def add_documents(self, index_uid, documents, *, primary_key):
        self.added = (index_uid, documents, primary_key)
        return TaskInfo(
            task_uid=4,
            status=TaskStatus.ENQUEUED,
            type="documentAdditionOrUpdate",
            enqueued_at=datetime.now(UTC),
        )

    async def aclose(self):
        self.closed = True


def test_adapter_uses_full_replacement_and_serializable_payload() -> None:
    asyncio.run(_assert_adapter_replacement())


async def _assert_adapter_replacement() -> None:
    client = FakeClient()
    adapter = MeilisearchCardSearch(client, index_uid="cards")
    document = CardSearchDocument(
        card_id=7,
        ygo_id=6983839,
        name="Tornado Dragon",
        text="text",
        card_type="XYZ Monster",
        race="Wyrm",
        attribute="WIND",
        sets=TORNADO["sets"],
        images=TORNADO["images"],
        source_updated_at=datetime.now(UTC),
    )
    result = await adapter.replace([document])
    assert isinstance(result, Ok)
    assert client.added[2] == "card_id"
    assert client.added[1][0]["sets"][0]["set_price"] == "4.08"
    await adapter.close()
    assert client.closed


def test_openapi_exposes_search_and_typed_arrays() -> None:
    schema = app.openapi()
    assert "/cards/search" in schema["paths"]
    card_create = schema["components"]["schemas"]["CardCreate"]
    assert "CardSet" in card_create["properties"]["sets"]["items"]["$ref"]


class FakeSearchBackend:
    async def search(self, query, *, page, shows):
        assert query == "Tornado"
        return Ok(
            {
                "items": [],
                "total": 0,
                "page": page,
                "shows": shows,
                "degraded": False,
            }
        )


def test_cards_search_endpoint_uses_search_dependency() -> None:
    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_card_search] = lambda: FakeSearchBackend()
    try:
        response = TestClient(app).get("/cards/search", params={"query": "Tornado"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "items": [], "total": 0, "page": 1, "shows": 20, "degraded": False
    }
