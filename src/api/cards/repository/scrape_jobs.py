from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, or_, select, text
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from .model import Card, ScrapeJob, ScrapeTarget

ACTIVE_JOB_STATUSES = ("pending", "running", "retry_wait")


def build_job_insert(
    *,
    target_id: int,
    priority: int,
    available_at: datetime | None = None,
) -> Insert:
    return (
        insert(ScrapeJob)
        .values(
            id=uuid4(),
            target_id=target_id,
            priority=priority,
            status="pending",
            available_at=available_at or datetime.now(UTC),
        )
        .on_conflict_do_nothing(
            index_elements=[ScrapeJob.target_id],
            index_where=text("status IN ('pending', 'running', 'retry_wait')"),
        )
        .returning(ScrapeJob.id)
    )


async def enqueue_for_card(
    db: AsyncSession,
    card: Card,
    *,
    priority: int = 0,
    now: datetime | None = None,
) -> ScrapeJob | None:
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
            where=ScrapeTarget.is_enabled.is_(True),
        )
        .returning(ScrapeTarget.id)
    )
    target_id = (await db.execute(target_insert)).scalar_one_or_none()

    if target_id is None:
        await db.rollback()

        return None

    job_insert = build_job_insert(
        target_id=target_id,
        priority=priority,
        available_at=requested_at,
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


def build_claim_statement(claimed_at: datetime) -> Select[tuple[ScrapeJob]]:
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

    return (
        select(ScrapeJob)
        .where(claimable)
        .order_by(ScrapeJob.priority.desc(), ScrapeJob.available_at.asc())
        # ScrapeJob.target is joined eagerly with a LEFT OUTER JOIN. PostgreSQL
        # rejects locking the nullable side, so only the queue row is locked.
        .with_for_update(skip_locked=True, of=ScrapeJob)
        .limit(1)
    )


async def claim_next_job(
    db: AsyncSession,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> ScrapeJob | None:
    claimed_at = now or datetime.now(UTC)
    statement = build_claim_statement(claimed_at)
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
    in_stock_count: int,
    next_refresh_at: datetime | None,
    now: datetime | None = None,
) -> None:
    finished_at = now or datetime.now(UTC)
    job = (
        await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.id == job_id)
            .with_for_update(of=ScrapeJob)
        )
    ).scalar_one()

    job.status = "succeeded"
    job.finished_at = finished_at
    job.lease_expires_at = None
    job.target.last_succeeded_at = finished_at
    job.target.next_refresh_at = next_refresh_at
    job.target.last_result_count = result_count
    job.target.last_in_stock_count = in_stock_count


async def mark_job_failed(
    db: AsyncSession,
    job_id: UUID,
    *,
    error_code: str,
    max_attempts: int,
    retry_delay_seconds: int,
    terminal: bool = False,
    disable_target: bool = False,
    now: datetime | None = None,
) -> str:
    failed_at = now or datetime.now(UTC)
    job = (
        await db.execute(
            select(ScrapeJob)
            .where(ScrapeJob.id == job_id)
            .with_for_update(of=ScrapeJob)
        )
    ).scalar_one()
    is_terminal = terminal or job.attempts >= max_attempts
    job.status = "failed" if is_terminal else "retry_wait"
    job.error_code = error_code
    job.lease_expires_at = None

    if is_terminal:
        job.finished_at = failed_at
    else:
        job.available_at = failed_at + timedelta(seconds=retry_delay_seconds)

    if disable_target:
        job.target.is_enabled = False
        job.target.disabled_reason = error_code
        job.target.disabled_at = failed_at
        job.target.next_refresh_at = None

    await db.commit()

    return job.status


async def reset_target(
    db: AsyncSession,
    *,
    card_id: int | None = None,
    ygo_id: int | None = None,
) -> ScrapeTarget | None:
    if (card_id is None) == (ygo_id is None):
        raise ValueError("Provide exactly one of card_id or ygo_id")

    predicate = (
        ScrapeTarget.card_id == card_id
        if card_id is not None
        else ScrapeTarget.ygo_id == ygo_id
    )
    target = (
        await db.execute(select(ScrapeTarget).where(predicate).with_for_update())
    ).scalar_one_or_none()

    if target is None:
        await db.rollback()

        return None

    target.is_enabled = True
    target.disabled_reason = None
    target.disabled_at = None
    target.next_refresh_at = None
    await db.commit()

    return target


async def backlog_size(db: AsyncSession) -> int:
    from sqlalchemy import func

    return (
        await db.execute(
            select(func.count())
            .select_from(ScrapeJob)
            .where(ScrapeJob.status.in_(ACTIVE_JOB_STATUSES))
        )
    ).scalar_one()
