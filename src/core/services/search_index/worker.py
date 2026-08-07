from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from uuid import UUID

from src.api.cards.application.search import CardSearch
from src.api.cards.application.search_deps import create_card_search
from src.api.cards.application.search_documents import card_to_search_document
from src.api.cards.repository import dao_cards
from src.api.cards.repository.model import SearchIndexEvent
from src.api.cards.repository.search_index_events import (
    claim_events,
    mark_retry,
    mark_succeeded,
    save_task_uid,
)
from src.core import Err, Ok
from src.core.db.deps import async_session_factory
from src.settings.search_settings import SearchSettings, search_settings

logger = logging.getLogger("free_win.search_index_worker")


class SearchIndexWorker:
    def __init__(
        self,
        search: CardSearch,
        *,
        settings: SearchSettings = search_settings,
    ) -> None:
        self.search = search
        self.settings = settings

    async def close(self) -> None:
        await self.search.close()

    async def process_once(self) -> bool:
        async with async_session_factory() as db:
            events = await claim_events(
                db,
                limit=self.settings.outbox_batch_size,
                lease_seconds=self.settings.outbox_lease_seconds,
            )

        if not events:
            return False

        fresh: list[SearchIndexEvent] = []

        for event in events:
            if event.remote_task_uid is None:
                fresh.append(event)

                continue

            result = await self.search.wait_for_task(event.remote_task_uid)

            async with async_session_factory() as db:
                if isinstance(result, Ok):
                    await mark_succeeded(db, [event.id])
                else:
                    await self._retry(
                        db,
                        [event.id],
                        result.error.code,
                        event.attempts,
                        clear_task_uid=result.error.code
                        in {
                            "MeilisearchTaskFailedError",
                            "MeilisearchTaskCanceledError",
                        },
                    )

        if not fresh:
            return True

        grouped: dict[int, list[UUID]] = defaultdict(list)

        for event in fresh:
            grouped[event.card_id].append(event.id)

        card_ids = list(grouped)

        async with async_session_factory() as db:
            cards = await dao_cards.get_many_by_ids(db, card_ids)

        by_id = {card.id: card for card in cards}
        existing_ids = [card_id for card_id in card_ids if card_id in by_id]
        deleted_ids = [card_id for card_id in card_ids if card_id not in by_id]

        if existing_ids:
            documents = [
                card_to_search_document(by_id[card_id]) for card_id in existing_ids
            ]
            await self._submit(
                [event_id for card_id in existing_ids for event_id in grouped[card_id]],
                self.search.replace(documents),
                max(event.attempts for event in fresh if event.card_id in existing_ids),
            )

        if deleted_ids:
            await self._submit(
                [event_id for card_id in deleted_ids for event_id in grouped[card_id]],
                self.search.delete(deleted_ids),
                max(event.attempts for event in fresh if event.card_id in deleted_ids),
            )

        return True

    async def _submit(self, event_ids, operation, attempts: int) -> None:
        result = await operation

        if isinstance(result, Err):
            async with async_session_factory() as db:
                await self._retry(db, event_ids, result.error.code, attempts)

            return
        task = result.value

        if task is None:
            async with async_session_factory() as db:
                await mark_succeeded(db, event_ids)

            return

        async with async_session_factory() as db:
            await save_task_uid(db, event_ids, task.task_uid)

        completed = await self.search.wait_for_task(task.task_uid)

        async with async_session_factory() as db:
            if isinstance(completed, Ok):
                await mark_succeeded(db, event_ids)
            else:
                await self._retry(
                    db,
                    event_ids,
                    completed.error.code,
                    attempts,
                    clear_task_uid=completed.error.code
                    in {"MeilisearchTaskFailedError", "MeilisearchTaskCanceledError"},
                )

    async def _retry(
        self,
        db,
        event_ids,
        code: str,
        attempts: int,
        *,
        clear_task_uid: bool = False,
    ) -> None:
        delay = self.settings.outbox_backoff_seconds * (2 ** min(attempts - 1, 8))
        await mark_retry(
            db,
            event_ids,
            error_code=code,
            backoff_seconds=delay,
            clear_task_uid=clear_task_uid,
        )

    async def run_forever(self) -> None:
        while True:
            try:
                processed = await self.process_once()
            except Exception:
                logger.exception("unexpected search index worker failure")
                processed = True

            if not processed:
                await asyncio.sleep(self.settings.outbox_poll_seconds)


def create_worker() -> SearchIndexWorker:
    search = create_card_search()

    if search is None:
        raise RuntimeError(
            "SEARCH_BACKEND=meilisearch is required for the index worker"
        )

    return SearchIndexWorker(search)
