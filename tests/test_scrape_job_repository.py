from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects import postgresql

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+asyncpg://test:test@localhost:5432/free_win_test",
)

from src.api.cards.repository.model import ScrapeJob  # noqa: E402
from src.api.cards.repository.scrape_jobs import (  # noqa: E402
    build_claim_statement,
    build_job_insert,
)


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
