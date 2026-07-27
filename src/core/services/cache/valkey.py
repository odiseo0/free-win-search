from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, cast


class AsyncValkeyClient(Protocol):
    async def ping(self) -> bool: ...

    async def get(self, key: str) -> str | bytes | None: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool: ...

    async def delete(self, *keys: str | bytes) -> int: ...

    def scan_iter(
        self,
        *,
        match: str,
        count: int,
    ) -> AsyncIterator[str | bytes]: ...

    async def aclose(self) -> None: ...


class ValkeyCache:
    _DELETE_BATCH_SIZE = 100

    def __init__(
        self,
        client: AsyncValkeyClient,
        *,
        key_prefix: str = "free-win:",
    ) -> None:
        self._client = client
        self._key_prefix = key_prefix

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        key_prefix: str = "free-win:",
        socket_timeout_seconds: float = 2.0,
        socket_connect_timeout_seconds: float = 2.0,
    ) -> ValkeyCache:
        # Importing lazily keeps the in-memory provider usable before the optional
        # local Valkey environment is available.
        # also using `cast` to keep autocomplete on :)
        from valkey.asyncio import Valkey

        client = cast(
            AsyncValkeyClient,
            Valkey.from_url(
                url,
                decode_responses=True,
                socket_timeout=socket_timeout_seconds,
                socket_connect_timeout=socket_connect_timeout_seconds,
                health_check_interval=30,
            ),
        )

        return cls(client, key_prefix=key_prefix)

    async def start(self) -> None:
        await self._client.ping()

    async def get(self, key: str) -> str | None:
        value = await self._client.get(self._key(key))

        if isinstance(value, bytes):
            return value.decode()

        return value

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        await self._client.set(self._key(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def delete_prefix(self, prefix: str) -> None:
        keys: list[str | bytes] = []
        pattern = f"{self._key(prefix)}*"

        async for key in self._client.scan_iter(
            match=pattern,
            count=self._DELETE_BATCH_SIZE,
        ):
            keys.append(key)

            if len(keys) == self._DELETE_BATCH_SIZE:
                await self._client.delete(*keys)
                keys.clear()

        if keys:
            await self._client.delete(*keys)

    async def close(self) -> None:
        await self._client.aclose()

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}{key}"
