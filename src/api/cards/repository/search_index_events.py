from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .model import SearchIndexEvent


async def enqueue_card(db: AsyncSession, card_id: int) -> SearchIndexEvent:
    event = SearchIndexEvent(card_id=card_id)
    db.add(event)

    await db.flush()

    return event


async def claim_events(
    db: AsyncSession, *, limit: int, lease_seconds: int
) -> list[SearchIndexEvent]:
    now = datetime.now(UTC)
    eligible = or_(
        SearchIndexEvent.status.in_(["pending", "retry_wait"]),
        (SearchIndexEvent.status == "running")
        & (SearchIndexEvent.lease_expires_at < now),
    )
    rows = list(
        (
            await db.execute(
                select(SearchIndexEvent)
                .where(eligible, SearchIndexEvent.available_at <= now)
                .order_by(SearchIndexEvent.available_at, SearchIndexEvent.date_added)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    lease = now + timedelta(seconds=lease_seconds)

    for event in rows:
        event.status = "running"
        event.attempts += 1
        event.lease_expires_at = lease

    await db.commit()

    return rows


async def save_task_uid(db: AsyncSession, event_ids: list[UUID], task_uid: int) -> None:
    await db.execute(
        update(SearchIndexEvent)
        .where(SearchIndexEvent.id.in_(event_ids))
        .values(remote_task_uid=task_uid)
    )
    await db.commit()


async def mark_succeeded(db: AsyncSession, event_ids: list[UUID]) -> None:
    await db.execute(
        update(SearchIndexEvent)
        .where(SearchIndexEvent.id.in_(event_ids))
        .values(
            status="succeeded",
            lease_expires_at=None,
            last_error=None,
            finished_at=func.now(),
        )
    )
    await db.commit()


async def mark_retry(
    db: AsyncSession,
    event_ids: list[UUID],
    *,
    error_code: str,
    backoff_seconds: int,
    clear_task_uid: bool = False,
) -> None:
    values = {
        "status": "retry_wait",
        "available_at": func.now() + timedelta(seconds=backoff_seconds),
        "lease_expires_at": None,
        "last_error": error_code[:255],
    }

    if clear_task_uid:
        values["remote_task_uid"] = None

    await db.execute(
        update(SearchIndexEvent)
        .where(SearchIndexEvent.id.in_(event_ids))
        .values(**values)
    )

    await db.commit()
