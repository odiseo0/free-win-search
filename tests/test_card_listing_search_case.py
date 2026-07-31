from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+asyncpg://test:test@localhost:5432/free_win_test",
)

from src.api.cards.application import card_listing_cases as cases  # noqa: E402
from src.api.cards.domain import ScrapeAcceptedResponse  # noqa: E402
from src.core import Ok  # noqa: E402


class ScalarResult:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object:
        return self.value


class FakeDB:
    def __init__(self, target: object = None) -> None:
        self.target = target

    async def execute(self, _: object) -> ScalarResult:
        return ScalarResult(self.target)


def listing() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        card_id=10,
        ygo_id=46986414,
        source="coolstuffinc",
        ygo_set="Legend of Blue Eyes",
        name="Dark Magician",
        code="LOB-005",
        price=Decimal("12.50"),
        rarity="Ultra Rare",
        condition="Near Mint",
        currency="USD",
        stock=3,
        last_seen_at=datetime.now(UTC),
        is_active=True,
        date_added=datetime.now(UTC),
        date_updated=None,
    )


def test_cold_miss_returns_job_and_stale_data_revalidates(
    monkeypatch,
) -> None:
    card = SimpleNamespace(id=10, ygo_id=46986414, name="Dark Magician")
    job_id = uuid4()
    enqueued: list[int] = []

    async def no_cache(*_: object, **__: object):
        return None

    async def no_op(*_: object, **__: object) -> None:
        return None

    async def resolve(*_: object, **__: object):
        return card

    async def enqueue(*_: object, **__: object):
        enqueued.append(card.id)
        return SimpleNamespace(id=job_id, status="pending")

    monkeypatch.setattr(cases, "get_cached_models", no_cache)
    monkeypatch.setattr(cases, "set_cached_models", no_op)
    monkeypatch.setattr(cases.dao_cards, "resolve_canonical", resolve)
    monkeypatch.setattr(cases, "enqueue_for_card", enqueue)

    async def run_cold():
        async def no_rows(*_: object, **__: object):
            return []

        monkeypatch.setattr(cases.dao, "for_card", no_rows)
        return await cases.search(FakeDB(), SimpleNamespace(), "Dark Magician")

    cold = asyncio.run(run_cold())
    assert isinstance(cold, Ok)
    assert isinstance(cold.value, ScrapeAcceptedResponse)
    assert cold.value.job_id == job_id

    async def run_stale():
        async def rows(*_: object, **__: object):
            return [listing()]

        monkeypatch.setattr(cases.dao, "for_card", rows)
        stale_target = SimpleNamespace(
            next_refresh_at=datetime.now(UTC) - timedelta(seconds=1),
            is_enabled=True,
        )
        return await cases.search(
            FakeDB(stale_target), SimpleNamespace(), "Dark Magician"
        )

    stale = asyncio.run(run_stale())
    assert isinstance(stale, Ok)
    assert isinstance(stale.value, list)
    assert stale.value[0].code == "LOB-005"
    assert enqueued == [10, 10]


def test_unknown_query_never_enqueues(monkeypatch) -> None:
    async def no_cache(*_: object, **__: object):
        return None

    async def no_op(*_: object, **__: object) -> None:
        return None

    async def unresolved(*_: object, **__: object):
        return None

    async def existing(*_: object, **__: object):
        return [listing()]

    async def forbidden_enqueue(*_: object, **__: object):
        raise AssertionError("Ambiguous input must not enqueue")

    monkeypatch.setattr(cases, "get_cached_models", no_cache)
    monkeypatch.setattr(cases, "set_cached_models", no_op)
    monkeypatch.setattr(cases.dao_cards, "resolve_canonical", unresolved)
    monkeypatch.setattr(cases.dao, "search_by_name", existing)
    monkeypatch.setattr(cases, "enqueue_for_card", forbidden_enqueue)

    result = asyncio.run(
        cases.search(FakeDB(), SimpleNamespace(), "dark", limit=10)
    )
    assert isinstance(result, Ok)
    assert isinstance(result.value, list)
    assert result.value[0].ygo_id == 46986414


def test_disabled_404_target_never_enqueues(monkeypatch) -> None:
    card = SimpleNamespace(id=10, ygo_id=46986414, name="Dark Magician")

    async def no_cache(*_: object, **__: object):
        return None

    async def no_op(*_: object, **__: object) -> None:
        return None

    async def resolve(*_: object, **__: object):
        return card

    async def no_rows(*_: object, **__: object):
        return []

    async def forbidden_enqueue(*_: object, **__: object):
        raise AssertionError("A disabled target must not enqueue")

    monkeypatch.setattr(cases, "get_cached_models", no_cache)
    monkeypatch.setattr(cases, "set_cached_models", no_op)
    monkeypatch.setattr(cases.dao_cards, "resolve_canonical", resolve)
    monkeypatch.setattr(cases.dao, "for_card", no_rows)
    monkeypatch.setattr(cases, "enqueue_for_card", forbidden_enqueue)

    target = SimpleNamespace(is_enabled=False, next_refresh_at=None)
    result = asyncio.run(cases.search(FakeDB(target), SimpleNamespace(), card.name))

    assert isinstance(result, Ok)
    assert result.value == []
