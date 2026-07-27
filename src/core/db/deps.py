from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from .session import async_session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as db:
        try:
            yield db
        finally:
            await db.close()


@asynccontextmanager
async def session() -> AsyncGenerator[AsyncSession]:
    """Use this in case you can't use dependency injection."""
    async with async_session_factory() as db:
        yield db
