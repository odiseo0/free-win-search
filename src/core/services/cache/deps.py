from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Cache
from .memory import InMemoryCache
from .valkey import ValkeyCache

if TYPE_CHECKING:
    from src.settings.cache_settings import CacheSettings

_cache: Cache | None = None


def create_cache(settings: CacheSettings) -> Cache:
    from src.settings.api_settings import api_settings

    if api_settings.environment == "production" and settings.backend != "valkey":
        raise RuntimeError("Production requires CACHE_BACKEND=valkey")

    if settings.backend == "valkey":
        return ValkeyCache.from_url(
            settings.url.get_secret_value(),
            key_prefix=settings.key_prefix,
            socket_timeout_seconds=settings.socket_timeout_seconds,
            socket_connect_timeout_seconds=settings.socket_connect_timeout_seconds,
        )

    return InMemoryCache()


def get_cache() -> Cache:
    global _cache

    if _cache is None:
        from src.settings.cache_settings import cache_settings

        _cache = create_cache(cache_settings)

    return _cache


async def close_cache() -> None:
    global _cache

    if _cache is None:
        return

    cache = _cache
    _cache = None
    await cache.close()
