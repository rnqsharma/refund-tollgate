from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return `value` as an aware UTC datetime.

    Postgres returns aware datetimes for TIMESTAMPTZ; SQLite returns naive ones that we always
    wrote in UTC. Treating naive as UTC makes comparisons behave the same on both.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
