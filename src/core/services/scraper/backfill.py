from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.cards.repository.model import Card, CardListing, ScrapeJob, ScrapeTarget
from src.api.cards.repository.scrape_jobs import ACTIVE_JOB_STATUSES, build_job_insert
from src.core.db.deps import async_session_factory
from src.core.utils.utils import datetime_now
from src.settings.scraper_settings import ScraperSettings, scraper_settings

logger = logging.getLogger("free_win.scraper_backfill")
STATE_VERSION = 3


class BackfillStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackfillConfig:
    batch_size: int = 50
    min_interval_minutes: int = 5
    max_interval_minutes: int = 30
    priority: int = -10

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= 50:
            raise ValueError("batch_size must be between 1 and 50")

        if self.min_interval_minutes < 1:
            raise ValueError("min_interval_minutes must be positive")

        if self.max_interval_minutes < self.min_interval_minutes:
            raise ValueError(
                "max_interval_minutes must be greater than or equal to the minimum"
            )


@dataclass(slots=True)
class BackfillState:
    version: int
    run_id: str
    status: str
    started_at: str
    updated_at: str
    completed_at: str | None
    last_card_id: int
    next_batch_available_at: str
    config: dict[str, int]
    batches_committed: int = 0
    jobs_created: int = 0
    jobs_reused: int = 0
    cards_skipped: int = 0
    error: str | None = None

    @classmethod
    def new(cls, config: BackfillConfig, now: datetime) -> BackfillState:
        timestamp = now.isoformat()

        return cls(
            version=STATE_VERSION,
            run_id=str(uuid4()),
            status="running",
            started_at=timestamp,
            updated_at=timestamp,
            completed_at=None,
            last_card_id=0,
            next_batch_available_at=timestamp,
            config=asdict(config),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BackfillState:
        value = dict(value)

        if value.get("version") == 1:
            value["version"] = STATE_VERSION

        if value.get("version") == 2:
            last_job_available_at = value.pop("last_job_available_at", None)
            max_interval = int(
                value.get("config", {}).get("max_interval_minutes", 30)
            )

            if last_job_available_at is None:
                value["next_batch_available_at"] = value["updated_at"]
            else:
                value["next_batch_available_at"] = (
                    datetime.fromisoformat(last_job_available_at)
                    + timedelta(minutes=max_interval)
                ).isoformat()

            value["version"] = STATE_VERSION

        try:
            state = cls(**value)
        except (TypeError, ValueError) as exc:
            raise BackfillStateError("Invalid backfill checkpoint") from exc

        if state.version != STATE_VERSION:
            raise BackfillStateError(f"Unsupported checkpoint version: {state.version}")

        return state


@dataclass(frozen=True, slots=True)
class EnqueueBatchResult:
    jobs_created: int
    jobs_reused: int
    cards_skipped: int


@dataclass(frozen=True, slots=True)
class BackfillResult:
    run_id: str
    status: str
    batches_committed: int
    jobs_created: int
    jobs_reused: int
    cards_skipped: int
    eligible_cards: int | None = None


def _write_state(path: Path, state: BackfillState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        temporary.write_text(
            json.dumps(asdict(state), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_state(path: Path) -> BackfillState | None:
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackfillStateError(f"Cannot read checkpoint {path}") from exc

    if not isinstance(raw, dict):
        raise BackfillStateError("Backfill checkpoint must contain a JSON object")

    return BackfillState.from_dict(raw)


def _archive_state(path: Path, now: datetime) -> Path | None:
    if not path.exists():
        return None

    suffix = now.strftime("%Y%m%dT%H%M%SZ")
    archived = path.with_name(f"{path.stem}.{suffix}.json")
    os.replace(path, archived)

    return archived


def build_missing_cards_statement(
    *,
    after_card_id: int,
    limit: int,
    now: datetime,
) -> Select[tuple[Card]]:
    has_listing = exists(select(CardListing.id).where(CardListing.card_id == Card.id))
    has_active_job = exists(
        select(ScrapeJob.id)
        .join(ScrapeTarget, ScrapeTarget.id == ScrapeJob.target_id)
        .where(
            ScrapeTarget.card_id == Card.id,
            ScrapeJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    eligible_target = or_(
        ScrapeTarget.id.is_(None),
        and_(
            ScrapeTarget.is_enabled.is_(True),
            or_(
                ScrapeTarget.next_refresh_at.is_(None),
                ScrapeTarget.next_refresh_at <= now,
            ),
        ),
    )

    return (
        select(Card)
        .outerjoin(ScrapeTarget, ScrapeTarget.card_id == Card.id)
        .where(
            Card.id > after_card_id,
            ~has_listing,
            ~has_active_job,
            eligible_target,
        )
        .order_by(Card.id.asc())
        .limit(limit)
    )


async def find_missing_cards(
    db: AsyncSession,
    *,
    after_card_id: int,
    limit: int,
    now: datetime,
) -> list[Card]:
    statement = build_missing_cards_statement(
        after_card_id=after_card_id,
        limit=limit,
        now=now,
    )

    return list((await db.execute(statement)).unique().scalars().all())


async def count_missing_cards(db: AsyncSession, *, now: datetime) -> int:
    statement = build_missing_cards_statement(
        after_card_id=0,
        limit=2_147_483_647,
        now=now,
    )

    result = await db.execute(select(func.count()).select_from(statement.subquery()))

    return int(result.scalar_one())


async def enqueue_card_batch(
    db: AsyncSession,
    cards: list[Card],
    *,
    priority: int,
    available_at: datetime,
    requested_at: datetime,
) -> EnqueueBatchResult:
    created = 0
    reused = 0
    skipped = 0

    for card in cards:
        target_statement = (
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
        target_id = (await db.execute(target_statement)).scalar_one_or_none()

        if target_id is None:
            skipped += 1

            continue

        job_id = (
            await db.execute(
                build_job_insert(
                    target_id=target_id,
                    priority=priority,
                    available_at=available_at,
                )
            )
        ).scalar_one_or_none()

        if job_id is None:
            reused += 1
        else:
            created += 1

    await db.commit()

    return EnqueueBatchResult(created, reused, skipped)


def _load_or_create_state(
    path: Path,
    config: BackfillConfig,
    now: datetime,
    *,
    restart: bool,
) -> BackfillState:
    state = _read_state(path)

    if restart and state is not None and state.status != "completed":
        _archive_state(path, now)
        state = None

    if state is None or state.status == "completed":
        state = BackfillState.new(config, now)
        _write_state(path, state)

        return state

    if state.config != asdict(config):
        raise BackfillStateError(
            "Checkpoint configuration differs from this invocation; use --restart"
        )

    state.status = "running"
    state.error = None
    state.updated_at = now.isoformat()
    _write_state(path, state)

    return state


async def run_missing_listings_backfill(
    *,
    state_path: Path,
    config: BackfillConfig,
    restart: bool = False,
    dry_run: bool = False,
    now_factory=datetime_now,
    rng: random.Random | None = None,
) -> BackfillResult:
    randomizer = rng or random.Random()
    now = now_factory()

    if dry_run:
        async with async_session_factory() as db:
            count = await count_missing_cards(db, now=now)

        return BackfillResult("dry-run", "dry_run", 0, 0, 0, 0, count)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(f"{state_path}.lock")

    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise BackfillStateError(
            f"Another backfill process is using {state_path}"
        ) from exc

    try:
        state = _load_or_create_state(state_path, config, now, restart=restart)

        try:
            while True:
                now = now_factory()

                async with async_session_factory() as db:
                    cards = await find_missing_cards(
                        db,
                        after_card_id=state.last_card_id,
                        limit=config.batch_size,
                        now=now,
                    )

                if not cards:
                    state.status = "completed"
                    state.completed_at = now.isoformat()
                    state.updated_at = now.isoformat()
                    _write_state(state_path, state)

                    break

                scheduled_at = max(
                    now, datetime.fromisoformat(state.next_batch_available_at)
                )

                async with async_session_factory() as db:
                    result = await enqueue_card_batch(
                        db,
                        cards,
                        priority=config.priority,
                        available_at=scheduled_at,
                        requested_at=now,
                    )

                state.last_card_id = cards[-1].id
                gap = randomizer.randint(
                    config.min_interval_minutes, config.max_interval_minutes
                )
                state.next_batch_available_at = (
                    scheduled_at + timedelta(minutes=gap)
                ).isoformat()
                state.batches_committed += 1
                state.jobs_created += result.jobs_created
                state.jobs_reused += result.jobs_reused
                state.cards_skipped += result.cards_skipped
                state.updated_at = now_factory().isoformat()
                _write_state(state_path, state)
                logger.info(
                    json.dumps(
                        {
                            "event": "backfill_batch_committed",
                            "run_id": state.run_id,
                            "batch": state.batches_committed,
                            "last_card_id": state.last_card_id,
                            "available_at": scheduled_at.isoformat(),
                            "jobs_created": result.jobs_created,
                        }
                    )
                )
        except BaseException as exc:
            failed_at = now_factory()
            state.status = (
                "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            )
            state.error = f"{type(exc).__name__}: {exc}"
            state.updated_at = failed_at.isoformat()
            _write_state(state_path, state)

            raise

        return BackfillResult(
            state.run_id,
            state.status,
            state.batches_committed,
            state.jobs_created,
            state.jobs_reused,
            state.cards_skipped,
        )
    finally:
        lock.release()


def config_from_settings(
    settings: ScraperSettings = scraper_settings,
) -> BackfillConfig:
    return BackfillConfig(
        batch_size=settings.backfill_batch_size,
        min_interval_minutes=settings.backfill_min_interval_minutes,
        max_interval_minutes=settings.backfill_max_interval_minutes,
        priority=settings.backfill_priority,
    )
