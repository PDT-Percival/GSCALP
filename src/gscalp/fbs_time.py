from __future__ import annotations

from datetime import datetime, timedelta, timezone


class FbsServerTimeError(ValueError):
    """Raised when an FBS server wall time has no unique UTC instant."""


def last_sunday_utc(year: int, month: int) -> datetime:
    if month not in {3, 10}:
        raise ValueError("month must be March or October")
    probe = datetime(year, month, 31, 1, tzinfo=timezone.utc)
    return probe - timedelta(days=(probe.weekday() + 1) % 7)


def fbs_utc_offset_at(value_utc: datetime) -> timedelta:
    if value_utc.tzinfo is None:
        raise ValueError("value_utc must be timezone-aware")
    value = value_utc.astimezone(timezone.utc)
    summer_start = last_sunday_utc(value.year, 3)
    summer_end = last_sunday_utc(value.year, 10)
    hours = 3 if summer_start <= value < summer_end else 2
    return timedelta(hours=hours)


def fbs_server_to_utc(value_server: datetime) -> datetime:
    if value_server.tzinfo is not None:
        raise ValueError("value_server must be a naive FBS wall time")

    candidates: list[datetime] = []
    for hours in (2, 3):
        candidate = (value_server - timedelta(hours=hours)).replace(
            tzinfo=timezone.utc
        )
        if fbs_utc_offset_at(candidate) == timedelta(hours=hours):
            candidates.append(candidate)

    if not candidates:
        raise FbsServerTimeError(
            f"nonexistent FBS server time: {value_server.isoformat(sep=' ')}"
        )
    if len(candidates) != 1:
        raise FbsServerTimeError(
            f"ambiguous FBS server time: {value_server.isoformat(sep=' ')}"
        )
    return candidates[0]
