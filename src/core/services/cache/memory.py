from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    value: str
    expires_at: float | None


class InMemoryCache:
    def __init__(self) -> None:
        self._entries: dict[str, _CacheEntry] = {}

    async def start(self) -> None:
        pass

    async def get(self, key: str) -> str | None:
        entry = self._entries.get(key)

        if entry is None:
            return None

        if entry.expires_at is not None and entry.expires_at <= monotonic():
            del self._entries[key]
            return None

        return entry.value

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        expires_at = None

        if ttl_seconds is not None:
            expires_at = monotonic() + ttl_seconds

        self._entries[key] = _CacheEntry(value=value, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        matching_keys = [key for key in self._entries if key.startswith(prefix)]

        for key in matching_keys:
            del self._entries[key]

    async def close(self) -> None:
        pass
