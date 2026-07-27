from typing import Protocol


class Cache(Protocol):
    async def start(self) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def delete_prefix(self, prefix: str) -> None: ...

    async def close(self) -> None: ...
