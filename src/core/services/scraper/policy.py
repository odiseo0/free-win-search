from datetime import datetime, timedelta


def next_refresh_at(
    now: datetime,
    *,
    in_stock_count: int,
) -> datetime:
    """Choose the next refresh from the observed inventory state."""
    hours = 1 if in_stock_count > 0 else 6

    return now + timedelta(hours=hours)
