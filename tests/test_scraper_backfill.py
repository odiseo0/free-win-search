from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from filelock import FileLock
from sqlalchemy.dialects import postgresql

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+asyncpg://test:test@localhost:5432/free_win_test",
)

from src.core.services.scraper.backfill import (  # noqa: E402
    BackfillConfig,
    BackfillState,
    BackfillStateError,
    EnqueueBatchResult,
    _load_or_create_state,
    _read_state,
    _write_state,
    build_missing_cards_statement,
    enqueue_card_batch,
    run_missing_listings_backfill,
)
from src.core.services.scraper import backfill as backfill_module  # noqa: E402


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class FakeDB:
    def __init__(self, values: list[object]) -> None:
        self.values = iter(values)
        self.statements: list[object] = []
        self.commits = 0

    async def execute(self, statement: object) -> ScalarResult:
        self.statements.append(statement)

        return ScalarResult(next(self.values))

    async def commit(self) -> None:
        self.commits += 1


def test_missing_cards_query_enforces_all_eligibility_rules() -> None:
    statement = build_missing_cards_statement(
        after_card_id=100,
        limit=50,
        now=datetime(2026, 7, 31, tzinfo=UTC),
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "cards.id > 100" in sql
    assert "NOT (EXISTS (SELECT card_listings.id" in sql
    assert "NOT (EXISTS (SELECT scrape_jobs.id" in sql
    assert "scrape_targets.is_enabled IS true" in sql
    assert "scrape_targets.next_refresh_at" in sql
    assert "LIMIT 50" in sql


def test_batch_enqueue_commits_once_and_uses_one_available_at() -> None:
    first_job = uuid4()
    second_job = uuid4()
    db = FakeDB([7, first_job, 8, second_job])
    cards = [
        SimpleNamespace(id=1, ygo_id=11, name="One"),
        SimpleNamespace(id=2, ygo_id=22, name="Two"),
    ]
    available_at = datetime(2026, 7, 31, 12, tzinfo=UTC)

    result = asyncio.run(
        enqueue_card_batch(
            db,  # type: ignore[arg-type]
            cards,  # type: ignore[arg-type]
            priority=-10,
            available_at=available_at,
            requested_at=available_at - timedelta(minutes=1),
        )
    )

    assert result.jobs_created == 2
    assert result.jobs_reused == 0
    assert db.commits == 1
    job_statements = [db.statements[1], db.statements[3]]
    for statement in job_statements:
        parameters = statement.compile(dialect=postgresql.dialect()).params
        assert parameters["available_at"] == available_at
        assert parameters["priority"] == -10


def test_checkpoint_is_atomic_and_resumes_an_incomplete_run(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    config = BackfillConfig()
    started = datetime(2026, 7, 31, tzinfo=UTC)
    state = BackfillState.new(config, started)
    state.last_card_id = 150
    state.jobs_created = 50
    state.status = "failed"
    _write_state(path, state)

    resumed = _load_or_create_state(
        path, config, started + timedelta(hours=1), restart=False
    )

    assert resumed.run_id == state.run_id
    assert resumed.last_card_id == 150
    assert resumed.jobs_created == 50
    assert resumed.status == "running"
    assert not list(tmp_path.glob("*.tmp"))


def test_completed_checkpoint_starts_a_new_full_pass(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    config = BackfillConfig()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    completed = BackfillState.new(config, now)
    completed.status = "completed"
    completed.last_card_id = 999
    _write_state(path, completed)

    new_state = _load_or_create_state(
        path, config, now + timedelta(hours=1), restart=False
    )

    assert new_state.run_id != completed.run_id
    assert new_state.last_card_id == 0


def test_checkpoint_config_mismatch_requires_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    now = datetime(2026, 7, 31, tzinfo=UTC)
    _write_state(path, BackfillState.new(BackfillConfig(), now))

    with pytest.raises(BackfillStateError, match="--restart"):
        _load_or_create_state(
            path,
            BackfillConfig(batch_size=25),
            now + timedelta(minutes=1),
            restart=False,
        )


def test_restart_archives_an_incomplete_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    config = BackfillConfig()
    now = datetime(2026, 7, 31, tzinfo=UTC)
    original = BackfillState.new(config, now)
    _write_state(path, original)

    restarted = _load_or_create_state(
        path, config, now + timedelta(minutes=1), restart=True
    )

    assert restarted.run_id != original.run_id
    archives = [item for item in tmp_path.glob("state.*.json") if item != path]
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())["run_id"] == original.run_id


def test_concurrent_scheduler_is_rejected_before_database_access(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    lock = FileLock(f"{path}.lock")
    lock.acquire(timeout=0)
    try:
        with pytest.raises(BackfillStateError, match="Another backfill"):
            asyncio.run(
                run_missing_listings_backfill(
                    state_path=path,
                    config=BackfillConfig(),
                )
            )
    finally:
        lock.release()


def test_read_state_rejects_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(BackfillStateError, match="Cannot read"):
        _read_state(path)


def test_scheduler_persists_batches_with_random_available_at_gaps(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "nested" / "state.json"
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    scheduled: list[datetime] = []

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    def session_factory():
        return SessionContext()

    async def find_cards(
        _db: object, *, after_card_id: int, **__: object
    ) -> list[SimpleNamespace]:
        if after_card_id == 0:
            return [SimpleNamespace(id=1)]
        if after_card_id == 1:
            return [SimpleNamespace(id=2)]

        return []

    async def enqueue(
        _db: object,
        _cards: object,
        *,
        available_at: datetime,
        **__: object,
    ) -> EnqueueBatchResult:
        scheduled.append(available_at)

        return EnqueueBatchResult(1, 0, 0)

    monkeypatch.setattr(backfill_module, "async_session_factory", session_factory)
    monkeypatch.setattr(backfill_module, "find_missing_cards", find_cards)
    monkeypatch.setattr(backfill_module, "enqueue_card_batch", enqueue)

    result = asyncio.run(
        run_missing_listings_backfill(
            state_path=path,
            config=BackfillConfig(
                batch_size=1,
                min_interval_minutes=5,
                max_interval_minutes=30,
            ),
            now_factory=lambda: now,
            rng=random.Random(7),
        )
    )
    checkpoint = _read_state(path)

    assert result.status == "completed"
    assert result.batches_committed == 2
    assert result.jobs_created == 2
    assert len(scheduled) == 2
    assert timedelta(minutes=5) <= scheduled[1] - scheduled[0] <= timedelta(
        minutes=30
    )
    assert checkpoint is not None
    assert checkpoint.last_card_id == 2
    assert checkpoint.status == "completed"


def test_fatal_scheduler_error_is_saved_for_resume(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "state.json"
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    async def fail(*_: object, **__: object):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        backfill_module, "async_session_factory", lambda: SessionContext()
    )
    monkeypatch.setattr(backfill_module, "find_missing_cards", fail)

    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(
            run_missing_listings_backfill(
                state_path=path,
                config=BackfillConfig(),
                now_factory=lambda: now,
            )
        )

    checkpoint = _read_state(path)
    assert checkpoint is not None
    assert checkpoint.status == "failed"
    assert checkpoint.last_card_id == 0
    assert checkpoint.error == "RuntimeError: database unavailable"
