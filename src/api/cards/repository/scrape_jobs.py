from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .model import Card, ScrapeJob, ScrapeTarget

ACTIVE_JOB_STATUSES = ("pending", "running", "retry_wait")


async def enqueue_for_card(
    db: AsyncSession,
    card: Card,
    *,
    priority: int = 0,
    now: datetime | None = None,
) -> ScrapeJob:
    requested_at = now or datetime.now(UTC)
    target_insert = (
        insert(ScrapeTarget)
        .values(
            card_id=card.id,
            ygo_id=card.ygo_id,
            canonical_name=card.name,
            last_requested_at=requested_at,
        )
        .on_conflict_do_update(
            index_elements=[ScrapeTarget.card_id],
            set_={
                "canonical_name": card.name,
                "ygo_id": card.ygo_id,
                "last_requested_at": requested_at,
            },
        )
        .returning(ScrapeTarget.id)
    )
    target_id = (await db.execute(target_insert)).scalar_one()

    job_insert = (
        insert(ScrapeJob)
        .values(
            target_id=target_id,
            priority=priority,
            status="pending",
            available_at=requested_at,
        )
        .on_conflict_do_nothing(
            index_elements=[ScrapeJob.target_id],
            index_where=text("status IN ('pending', 'running', 'retry_wait')"),
        )
        .returning(ScrapeJob.id)
    )
    job_id = (await db.execute(job_insert)).scalar_one_or_none()

    if job_id is None:
        job_id = (
            await db.execute(
                select(ScrapeJob.id).where(
                    ScrapeJob.target_id == target_id,
                    ScrapeJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).scalar_one()

    await db.commit()
    return (
        await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.id == job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def get_job(db: AsyncSession, job_id: UUID) -> ScrapeJob | None:
    return (
        await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
    ).scalar_one_or_none()


async def claim_next_job(
    db: AsyncSession,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> ScrapeJob | None:
    claimed_at = now or datetime.now(UTC)
    claimable = or_(
        and_(
            ScrapeJob.status.in_(("pending", "retry_wait")),
            ScrapeJob.available_at <= claimed_at,
        ),
        and_(
            ScrapeJob.status == "running",
            ScrapeJob.lease_expires_at <= claimed_at,
        ),
    )
    statement = (
        select(ScrapeJob)
        .where(claimable)
        .order_by(ScrapeJob.priority.desc(), ScrapeJob.available_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = (await db.execute(statement)).scalar_one_or_none()

    if job is None:
        await db.rollback()

        return None

    job.status = "running"
    job.attempts += 1
    job.started_at = claimed_at
    job.lease_expires_at = claimed_at + timedelta(seconds=lease_seconds)
    job.error_code = None

    await db.commit()

    return job


async def mark_job_succeeded(
    db: AsyncSession,
    job_id: UUID,
    *,
    result_count: int,
    next_refresh_at: datetime | None,
    now: datetime | None = None,
) -> None:
    finished_at = now or datetime.now(UTC)
    job = (
        await db.execute(
            select(ScrapeJob).where(ScrapeJob.id == job_id).with_for_update()
        )
    ).scalar_one()
    job.status = "succeeded"
    job.finished_at = finished_at
    job.lease_expires_at = None
    job.target.last_succeeded_at = finished_at
    job.target.next_refresh_at = next_refresh_at
    job.target.last_result_count = result_count


async def mark_job_failed(
    db: AsyncSession,
    job_id: UUID,
    *,
    error_code: str,
    max_attempts: int,
    retry_delay_seconds: int,
    now: datetime | None = None,
) -> str:
    failed_at = now or datetime.now(UTC)
    job = (
        await db.execute(
            select(ScrapeJob).where(ScrapeJob.id == job_id).with_for_update()
        )
    ).scalar_one()
    terminal = job.attempts >= max_attempts
    job.status = "failed" if terminal else "retry_wait"
    job.error_code = error_code
    job.lease_expires_at = None

    if terminal:
        job.finished_at = failed_at
    else:
        job.available_at = failed_at + timedelta(seconds=retry_delay_seconds)

    await db.commit()

    return job.status


async def backlog_size(db: AsyncSession) -> int:
    from sqlalchemy import func

    return (
        await db.execute(
            select(func.count())
            .select_from(ScrapeJob)
            .where(ScrapeJob.status.in_(ACTIVE_JOB_STATUSES))
        )
    ).scalar_one()
