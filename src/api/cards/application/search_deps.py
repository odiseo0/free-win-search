from __future__ import annotations

from src.core.services.meilisearch import MeilisearchClient
from src.settings.search_settings import SearchSettings, search_settings

from .search import CardSearch, MeilisearchCardSearch

_search: CardSearch | None = None


def create_card_search(settings: SearchSettings = search_settings) -> CardSearch | None:
    if settings.backend == "postgresql":
        return None

    if not settings.meilisearch_url:
        raise RuntimeError(
            "SEARCH_MEILISEARCH_URL is required when SEARCH_BACKEND=meilisearch"
        )

    client = MeilisearchClient(
        settings.meilisearch_url,
        settings.meilisearch_api_key.get_secret_value()
        if settings.meilisearch_api_key
        else None,
        timeout_seconds=settings.timeout_seconds,
        max_connections=settings.max_connections,
        max_concurrency=settings.max_concurrency,
        max_retries=settings.max_retries,
        retry_backoff_seconds=settings.retry_backoff_seconds,
        max_retry_delay_seconds=settings.max_retry_delay_seconds,
    )

    return MeilisearchCardSearch(
        client,
        index_uid=settings.index_uid,
        task_timeout_seconds=settings.task_timeout_seconds,
        task_poll_interval_seconds=settings.task_poll_interval_seconds,
    )


def get_card_search() -> CardSearch | None:
    global _search

    if _search is None:
        _search = create_card_search()

    return _search


async def close_card_search() -> None:
    global _search

    if _search is None:
        return

    search = _search
    _search = None

    await search.close()
