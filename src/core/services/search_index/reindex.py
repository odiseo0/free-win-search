from __future__ import annotations

from sqlalchemy import select

from src.api.cards.application.search import CardSearch
from src.api.cards.application.search_documents import card_to_search_document
from src.api.cards.repository.model import Card
from src.core import Err
from src.core.db.deps import async_session_factory


async def reindex_cards(search: CardSearch, *, batch_size: int = 100) -> int:
    last_id = 0
    indexed = 0

    while True:
        async with async_session_factory() as db:
            cards = list(
                (
                    await db.execute(
                        select(Card)
                        .where(Card.id > last_id)
                        .order_by(Card.id)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )

        if not cards:
            return indexed

        result = await search.replace([card_to_search_document(card) for card in cards])

        if isinstance(result, Err):
            raise TypeError(f"reindex submit failed: {result.error.code}")

        if result.value is not None:
            completed = await search.wait_for_task(result.value.task_uid)

            if isinstance(completed, Err):
                raise RuntimeError(f"reindex task failed: {completed.error.code}")

        indexed += len(cards)
        last_id = cards[-1].id
