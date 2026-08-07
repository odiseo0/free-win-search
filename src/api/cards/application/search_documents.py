from __future__ import annotations

from src.api.cards.domain import CardSearchDocument
from src.api.cards.repository.model import Card


def card_to_search_document(card: Card) -> CardSearchDocument:
    return CardSearchDocument(
        card_id=card.id,
        ygo_id=card.ygo_id,
        name=card.name,
        text=card.text,
        card_type=card.card_type,
        race=card.race,
        attribute=card.attribute,
        sets=card.sets,
        images=card.images,
        source_updated_at=card.date_updated or card.date_added,
        document_version=1,
    )
