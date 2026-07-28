from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

import pandas as pd


class NewsCode(str, Enum):
    CLEAR = "clear"
    MISSING_DATE_CONFIRMATION = "missing_date_confirmation"
    OVERLAPPING_BLACKOUT = "overlapping_blackout"
    INVALID_ROW = "invalid_row"


@dataclass(frozen=True, slots=True)
class NewsDecision:
    allowed: bool
    code: NewsCode
    matching_rows: tuple[dict[str, str], ...]


def _read_news_rows(path: Path | str) -> tuple[dict[str, str], ...]:
    try:
        with Path(path).open(encoding="utf-8", newline="") as stream:
            return tuple(dict(row) for row in csv.DictReader(stream))
    except (OSError, csv.Error):
        return ()


def _event_interval(
    row: Mapping[str, str],
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    try:
        start = pd.Timestamp(row["event_start_utc"])
        end = pd.Timestamp(row["event_end_utc"])
    except (KeyError, TypeError, ValueError):
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    if not row.get("source", "").strip():
        return None
    return start.tz_convert("UTC"), end.tz_convert("UTC")


def _overlaps(
    start: pd.Timestamp,
    end: pd.Timestamp,
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
) -> bool:
    return start < session_end and end > session_start


def _covers(
    start: pd.Timestamp,
    end: pd.Timestamp,
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
) -> bool:
    return start <= session_start and end >= session_end


def news_gate(
    path: Path | str,
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
    buffer: pd.Timedelta,
) -> NewsDecision:
    if session_start.tzinfo is None or session_end.tzinfo is None:
        raise ValueError("session_start and session_end must be timezone-aware")
    if session_end <= session_start:
        raise ValueError("session_end must be after session_start")
    if buffer < pd.Timedelta(0):
        raise ValueError("buffer must be nonnegative")

    buffered_start = session_start.tz_convert("UTC") - buffer
    buffered_end = session_end.tz_convert("UTC") + buffer
    rows = _read_news_rows(path)
    blackout_rows: list[dict[str, str]] = []
    clear_rows: list[dict[str, str]] = []

    for row in rows:
        interval = _event_interval(row)
        if interval is None:
            continue
        start, end = interval
        currency = row.get("currency", "").strip().upper()
        impact = row.get("impact", "").strip().lower()
        event_name = row.get("event_name", "").strip().upper()

        if (
            currency in {"USD", "XAU", "GOLD", "ALL"}
            and impact == "high"
            and _overlaps(start, end, buffered_start, buffered_end)
        ):
            blackout_rows.append(dict(row))
        if (
            event_name == "NO_HIGH_IMPACT_EVENTS"
            and _covers(start, end, buffered_start, buffered_end)
        ):
            clear_rows.append(dict(row))

    if blackout_rows:
        return NewsDecision(
            allowed=False,
            code=NewsCode.OVERLAPPING_BLACKOUT,
            matching_rows=tuple(blackout_rows),
        )
    if clear_rows:
        return NewsDecision(
            allowed=True,
            code=NewsCode.CLEAR,
            matching_rows=tuple(clear_rows),
        )
    return NewsDecision(
        allowed=False,
        code=NewsCode.MISSING_DATE_CONFIRMATION,
        matching_rows=(),
    )
