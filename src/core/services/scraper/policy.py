from datetime import datetime, timedelta


def next_refresh_at(
    last_requested_at: datetime,
    now: datetime,
) -> datetime | None:
    demand_age = now - last_requested_at

    if demand_age <= timedelta(hours=1):
        return now + timedelta(hours=1)

    if demand_age <= timedelta(hours=6):
        return now + timedelta(hours=3)

    if demand_age <= timedelta(hours=24):
        return now + timedelta(hours=6)

    return None
