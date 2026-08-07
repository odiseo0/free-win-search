from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from src.api.cards.domain import CardSearchDocument, CardSearchResponse
from src.core import Err, Ok, Result
from src.core.services.meilisearch import (
    MeilisearchApiError,
    MeilisearchClient,
    MeilisearchCommunicationError,
    MeilisearchError,
    SearchQuery,
    Task,
    TaskInfo,
)


@dataclass(frozen=True, slots=True)
class CardSearchError:
    code: str
    retryable: bool


class CardSearch(Protocol):
    async def search(
        self, query: str, *, page: int, shows: int
    ) -> Result[CardSearchResponse, CardSearchError]: ...

    async def replace(
        self, documents: list[CardSearchDocument]
    ) -> Result[TaskInfo | None, CardSearchError]: ...

    async def delete(
        self, card_ids: list[int]
    ) -> Result[TaskInfo | None, CardSearchError]: ...

    async def get_task(self, task_uid: int) -> Result[Task, CardSearchError]: ...

    async def wait_for_task(self, task_uid: int) -> Result[Task, CardSearchError]: ...

    async def close(self) -> None: ...


class MeilisearchCardSearch:
    def __init__(
        self,
        client: MeilisearchClient,
        *,
        index_uid: str,
        task_timeout_seconds: float = 30.0,
        task_poll_interval_seconds: float = 0.1,
    ) -> None:
        self.client = client
        self.index_uid = index_uid
        self.task_timeout_seconds = task_timeout_seconds
        self.task_poll_interval_seconds = task_poll_interval_seconds

    async def search(
        self, query: str, *, page: int, shows: int
    ) -> Result[CardSearchResponse, CardSearchError]:
        try:
            result = await self.client.search(
                self.index_uid,
                SearchQuery(q=query, page=page, hits_per_page=shows),
            )
            items = [CardSearchDocument.model_validate(hit) for hit in result.hits]
            total = result.total_hits

            if total is None:
                total = result.estimated_total_hits or len(items)

            return Ok(
                CardSearchResponse(
                    items=items,
                    page=page,
                    shows=shows,
                    total=total,
                    degraded=False,
                )
            )
        except ValidationError:
            return Err(CardSearchError("invalid_hit", False))
        except MeilisearchError as error:
            return Err(_translate_error(error))

    async def replace(
        self, documents: list[CardSearchDocument]
    ) -> Result[TaskInfo | None, CardSearchError]:
        if not documents:
            return Ok(None)

        payloads = [document.model_dump(mode="json") for document in documents]

        try:
            return Ok(
                await self.client.add_documents(
                    self.index_uid, payloads, primary_key="card_id"
                )
            )
        except MeilisearchError as error:
            return Err(_translate_error(error))

    async def delete(
        self, card_ids: list[int]
    ) -> Result[TaskInfo | None, CardSearchError]:
        if not card_ids:
            return Ok(None)
        try:
            return Ok(await self.client.delete_documents(self.index_uid, card_ids))
        except MeilisearchError as error:
            return Err(_translate_error(error))

    async def get_task(self, task_uid: int) -> Result[Task, CardSearchError]:
        try:
            return Ok(await self.client.get_task(task_uid))
        except MeilisearchError as error:
            return Err(_translate_error(error))

    async def wait_for_task(self, task_uid: int) -> Result[Task, CardSearchError]:
        try:
            return Ok(
                await self.client.wait_for_task(
                    task_uid,
                    timeout_seconds=self.task_timeout_seconds,
                    poll_interval_seconds=self.task_poll_interval_seconds,
                )
            )
        except MeilisearchError as error:
            return Err(_translate_error(error))

    async def close(self) -> None:
        await self.client.aclose()


def _translate_error(error: MeilisearchError) -> CardSearchError:
    retryable = isinstance(error, MeilisearchCommunicationError) or (
        isinstance(error, MeilisearchApiError)
        and error.status_code in {408, 429, 500, 502, 503, 504}
    )
    code = error.code if isinstance(error, MeilisearchApiError) else None

    return CardSearchError(code or type(error).__name__, retryable)
