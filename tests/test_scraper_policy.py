from datetime import UTC, datetime, timedelta

from src.core.services.scraper.policy import next_refresh_at


def test_adaptive_refresh_policy() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert next_refresh_at(now - timedelta(minutes=30), now) == now + timedelta(hours=1)
    assert next_refresh_at(now - timedelta(hours=3), now) == now + timedelta(hours=3)
    assert next_refresh_at(now - timedelta(hours=12), now) == now + timedelta(hours=6)
    assert next_refresh_at(now - timedelta(days=2), now) is None
