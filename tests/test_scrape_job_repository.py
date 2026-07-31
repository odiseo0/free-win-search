from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy.dialects import postgresql

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+asyncpg://test:test@localhost:5432/free_win_test",
)

from src.api.cards.repository.model import ScrapeJob  # noqa: E402
from src.api.cards.repository.scrape_jobs import (  # noqa: E402
    build_claim_statement,
    build_job_insert,
    mark_job_failed,
)


class OneResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one(self) -> object:
        return self.value


class FailureDB:
    def __init__(self, job: object) -> None:
        self.job = job
        self.commits = 0

    async def execute(self, _: object) -> OneResult:
        return OneResult(self.job)

    async def commit(self) -> None:
        self.commits += 1


def test_scrape_job_id_has_a_python_insert_default() -> None:
    assert ScrapeJob.__table__.c.id.default is not None


def test_job_insert_always_contains_an_explicit_uuid() -> None:
    statement = build_job_insert(target_id=7, priority=0)
    parameters = statement.compile(
        dialect=postgresql.dialect()
    ).params

    assert isinstance(parameters["id"], UUID)
    assert parameters["target_id"] == 7


def test_claim_locks_only_scrape_jobs_and_skips_locked_rows() -> None:
    statement = build_claim_statement(datetime(2026, 7, 27, tzinfo=UTC))
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "LEFT OUTER JOIN scrape_targets" in sql
    assert "FOR UPDATE OF scrape_jobs SKIP LOCKED" in sql


def test_not_found_failure_is_terminal_and_disables_target() -> None:
    target = SimpleNamespace(
        is_enabled=True,
        disabled_reason=None,
        disabled_at=None,
        next_refresh_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    job = SimpleNamespace(
        attempts=1,
        target=target,
        status="running",
        error_code=None,
        lease_expires_at=datetime(2026, 7, 31, tzinfo=UTC),
        finished_at=None,
    )
    db = FailureDB(job)
    now = datetime(2026, 7, 31, tzinfo=UTC)

    status = asyncio.run(
        mark_job_failed(
            db,  # type: ignore[arg-type]
            uuid4(),
            error_code="not_found",
            max_attempts=4,
            retry_delay_seconds=60,
            terminal=True,
            disable_target=True,
            now=now,
        )
    )

    assert status == "failed"
    assert job.finished_at == now
    assert target.is_enabled is False
    assert target.disabled_reason == "not_found"
    assert target.disabled_at == now
    assert target.next_refresh_at is None
    assert db.commits == 1
