from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import pandas as pd

from .fbs_time import FbsServerTimeError, fbs_server_to_utc
from .mt5_calendar_raw import (
    CalendarExport,
    CalendarQueryKey,
    RawCalendarEvent,
)
from .news_sessions import CandidateSession


REQUIRED_FROM_SERVER = datetime(2020, 1, 1)
REQUIRED_TO_SERVER = datetime(2026, 8, 1)

REQUIRED_METADATA = {
    "script_version": "mt5-calendar-v1",
    "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
    "account_server": "FBS-Demo",
    "account_trade_mode": "0",
    "account_margin_mode": "2",
    "requested_from_server": "2020.01.01 00:00:00",
    "requested_to_server": "2026.08.01 00:00:00",
    "export_status": "complete",
}

TIME_MODE_CODES = {
    "CALENDAR_TIMEMODE_DATETIME": 0,
    "CALENDAR_TIMEMODE_DATE": 1,
    "CALENDAR_TIMEMODE_NOTIME": 2,
    "CALENDAR_TIMEMODE_TENTATIVE": 3,
}

IMPORTANCE_CODES = {
    "CALENDAR_IMPORTANCE_NONE": 0,
    "CALENDAR_IMPORTANCE_LOW": 1,
    "CALENDAR_IMPORTANCE_MODERATE": 2,
    "CALENDAR_IMPORTANCE_HIGH": 3,
}


class CalendarNormalizationError(ValueError):
    """Raised when complete source evidence cannot be normalized safely."""


@dataclass(frozen=True, slots=True, order=True)
class NormalizedNewsRow:
    event_start_utc: pd.Timestamp
    event_end_utc: pd.Timestamp
    currency: str
    impact: str
    event_name: str
    source: str

    def csv_dict(self) -> dict[str, str]:
        return {
            "event_start_utc": self.event_start_utc.isoformat(),
            "event_end_utc": self.event_end_utc.isoformat(),
            "currency": self.currency,
            "impact": self.impact,
            "event_name": self.event_name,
            "source": self.source,
        }


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1)
    return datetime(value.year, value.month + 1, 1)


def expected_monthly_queries(
    start_server: datetime,
    end_server: datetime,
) -> tuple[CalendarQueryKey, ...]:
    if start_server.tzinfo is not None or end_server.tzinfo is not None:
        raise ValueError("query range must use naive FBS server times")
    if end_server <= start_server:
        raise ValueError("end_server must be after start_server")
    if start_server.day != 1 or start_server.time() != datetime.min.time():
        raise ValueError("start_server must be the first second of a month")
    if end_server.day != 1 or end_server.time() != datetime.min.time():
        raise ValueError("end_server must be the first second of a month")

    keys: list[CalendarQueryKey] = []
    current = start_server
    while current < end_server:
        following = _next_month(current)
        if following > end_server:
            raise ValueError("end_server must be a complete month boundary")
        for currency in ("USD", "XAU"):
            keys.append(CalendarQueryKey(currency, current, following))
        current = following
    return tuple(keys)


def validate_complete_export(export: CalendarExport) -> None:
    metadata = export.metadata.values
    for field, expected in REQUIRED_METADATA.items():
        actual = metadata.get(field)
        if actual != expected:
            raise CalendarNormalizationError(
                f"{field} must be {expected!r}, got {actual!r}"
            )

    expected = expected_monthly_queries(REQUIRED_FROM_SERVER, REQUIRED_TO_SERVER)
    expected_set = set(expected)
    actual_keys = [query.key for query in export.queries]
    actual_set = set(actual_keys)
    if len(actual_keys) != len(actual_set):
        raise CalendarNormalizationError("duplicate query status keys")
    missing = sorted(expected_set - actual_set)
    if missing:
        raise CalendarNormalizationError(f"missing queries: {missing}")
    unexpected = sorted(actual_set - expected_set)
    if unexpected:
        raise CalendarNormalizationError(f"unexpected queries: {unexpected}")

    events_by_query: dict[CalendarQueryKey, int] = {}
    value_ids: set[int] = set()
    for event in export.events:
        if event.value_id in value_ids:
            raise CalendarNormalizationError(
                f"duplicate value ID: {event.value_id}"
            )
        value_ids.add(event.value_id)
        if event.query not in expected_set:
            raise CalendarNormalizationError(
                f"event references unexpected query: {event.query}"
            )
        if not event.query.start_server <= event.time_server < event.query.end_server:
            raise CalendarNormalizationError(
                f"event {event.value_id} is outside query interval"
            )
        if not event.event_name.strip():
            raise CalendarNormalizationError(
                f"event {event.value_id} has blank event_name"
            )
        if not event.source_url.strip():
            raise CalendarNormalizationError(
                f"event {event.value_id} has blank source_url"
            )
        events_by_query[event.query] = events_by_query.get(event.query, 0) + 1

    for query in export.queries:
        if query.error != 0:
            raise CalendarNormalizationError(
                f"query error {query.error} for {query.key}"
            )
        if query.count < 0:
            raise CalendarNormalizationError(
                f"negative query count for {query.key}"
            )
        actual_count = events_by_query.get(query.key, 0)
        if query.count != actual_count:
            raise CalendarNormalizationError(
                f"event count mismatch for {query.key}: "
                f"declared {query.count}, actual {actual_count}"
            )


def _validate_enum_pair(
    event: RawCalendarEvent,
    *,
    values: dict[str, int],
    name: str,
    code: int,
    label: str,
) -> None:
    expected = values.get(name)
    if expected is None or expected != code:
        raise CalendarNormalizationError(
            f"event {event.value_id} {label} code/name mismatch: {code}, {name}"
        )


def _event_interval(event: RawCalendarEvent) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        if event.time_mode_name == "CALENDAR_TIMEMODE_DATETIME":
            start = pd.Timestamp(fbs_server_to_utc(event.time_server))
            return start, start + pd.Timedelta(seconds=1)
        day_start = datetime.combine(event.time_server.date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)
        return (
            pd.Timestamp(fbs_server_to_utc(day_start)),
            pd.Timestamp(fbs_server_to_utc(day_end)),
        )
    except FbsServerTimeError as exc:
        raise CalendarNormalizationError(str(exc)) from exc


def _normalized_events(
    export: CalendarExport,
    raw_sha256: str,
) -> tuple[NormalizedNewsRow, ...]:
    rows: list[NormalizedNewsRow] = []
    for event in export.events:
        _validate_enum_pair(
            event,
            values=TIME_MODE_CODES,
            name=event.time_mode_name,
            code=event.time_mode_code,
            label="time mode",
        )
        _validate_enum_pair(
            event,
            values=IMPORTANCE_CODES,
            name=event.importance_name,
            code=event.importance_code,
            label="importance",
        )
        if event.importance_name != "CALENDAR_IMPORTANCE_HIGH":
            continue
        start, end = _event_interval(event)
        rows.append(
            NormalizedNewsRow(
                event_start_utc=start,
                event_end_utc=end,
                currency=event.query.currency,
                impact="high",
                event_name=event.event_name.strip(),
                source=(
                    f"MT5 Calendar event {event.event_id}; "
                    f"{event.source_url.strip()}; raw={raw_sha256}"
                ),
            )
        )
    return tuple(sorted(set(rows)))


def _query_covers_session(
    query: CalendarQueryKey,
    session: CandidateSession,
) -> bool:
    try:
        query_start = pd.Timestamp(fbs_server_to_utc(query.start_server))
        query_end = pd.Timestamp(fbs_server_to_utc(query.end_server))
    except FbsServerTimeError as exc:
        raise CalendarNormalizationError(str(exc)) from exc
    return query_start <= session.start_utc and query_end >= session.end_utc


def _clear_rows(
    export: CalendarExport,
    sessions: Sequence[CandidateSession],
    events: Sequence[NormalizedNewsRow],
    raw_sha256: str,
) -> tuple[NormalizedNewsRow, ...]:
    rows: list[NormalizedNewsRow] = []
    for session in sessions:
        if session.start_utc.tzinfo is None or session.end_utc.tzinfo is None:
            raise CalendarNormalizationError("candidate session must be timezone-aware")
        if session.end_utc <= session.start_utc:
            raise CalendarNormalizationError(
                "candidate session end must be after start"
            )
        for currency in ("USD", "XAU"):
            if not any(
                query.key.currency == currency
                and _query_covers_session(query.key, session)
                for query in export.queries
            ):
                raise CalendarNormalizationError(
                    f"{currency} queries do not cover {session.local_date} {session.window}"
                )
        overlapping = any(
            event.event_start_utc < session.end_utc
            and event.event_end_utc > session.start_utc
            for event in events
        )
        if overlapping:
            continue
        rows.append(
            NormalizedNewsRow(
                event_start_utc=session.start_utc.tz_convert("UTC"),
                event_end_utc=session.end_utc.tz_convert("UTC"),
                currency="ALL",
                impact="none",
                event_name="NO_HIGH_IMPACT_EVENTS",
                source=(
                    "MT5 Calendar complete USD+XAU queries; "
                    f"raw={raw_sha256}"
                ),
            )
        )
    return tuple(sorted(set(rows)))


def normalize_calendar_news(
    export: CalendarExport,
    sessions: Sequence[CandidateSession],
    raw_sha256: str,
) -> tuple[NormalizedNewsRow, ...]:
    validate_complete_export(export)
    if re.fullmatch(r"[0-9a-f]{64}", raw_sha256) is None:
        raise CalendarNormalizationError("raw SHA-256 must be 64 lowercase hex digits")
    events = _normalized_events(export, raw_sha256)
    clears = _clear_rows(export, sessions, events, raw_sha256)
    return tuple(sorted(set(events).union(clears)))
