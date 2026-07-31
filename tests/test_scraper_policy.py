from datetime import UTC, datetime, timedelta

from src.core.services.scraper.policy import next_refresh_at


def test_inventory_refresh_policy() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    assert next_refresh_at(now, in_stock_count=2) == now + timedelta(hours=1)
    assert next_refresh_at(now, in_stock_count=0) == now + timedelta(hours=6)
