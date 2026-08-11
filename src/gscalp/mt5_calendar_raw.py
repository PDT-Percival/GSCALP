from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


EVENT_FIELDS = (
    "query_currency",
    "query_start_server",
    "query_end_server",
    "query_count",
    "query_error",
    "value_id",
    "event_id",
    "event_time_server",
    "event_time_mode_code",
    "event_time_mode_name",
    "event_importance_code",
    "event_importance_name",
    "country_id",
    "event_code",
    "event_name",
    "source_url",
)

EVENT_ONLY_FIELDS = EVENT_FIELDS[5:]

METADATA_FIELDS = frozenset(
    {
        "script_version",
        "terminal_path",
        "terminal_build",
        "terminal_company",
        "account_server",
        "account_trade_mode",
        "account_margin_mode",
        "requested_from_server",
        "requested_to_server",
        "generated_at_server",
        "current_server_time",
        "current_gmt_time",
        "calendar_currencies",
        "export_status",
    }
)

FORBIDDEN_METADATA_FIELDS = frozenset(
    {
        "account_login",
        "login",
        "password",
        "account_name",
        "name",
        "balance",
        "equity",
    }
)

SERVER_TIME_FORMAT = "%Y.%m.%d %H:%M:%S"


class CalendarRawError(ValueError):
    """Raised when an MT5 calendar export violates the raw contract."""


@dataclass(frozen=True, slots=True, order=True)
class CalendarQueryKey:
    currency: str
    start_server: datetime
    end_server: datetime


@dataclass(frozen=True, slots=True)
class CalendarQueryStatus:
    key: CalendarQueryKey
    count: int
    error: int


@dataclass(frozen=True, slots=True)
class RawCalendarEvent:
    query: CalendarQueryKey
    value_id: int
    event_id: int
    time_server: datetime
    time_mode_code: int
    time_mode_name: str
    importance_code: int
    importance_name: str
    country_id: int
    event_code: str
    event_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class CalendarMetadata:
    values: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class CalendarExport:
    queries: tuple[CalendarQueryStatus, ...]
    events: tuple[RawCalendarEvent, ...]
    metadata: CalendarMetadata


def _parse_server_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.strptime(value, SERVER_TIME_FORMAT)
    except (TypeError, ValueError) as exc:
        raise CalendarRawError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise CalendarRawError(f"invalid {field}: must be a naive server time")
    return parsed


def _parse_int(value: str, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CalendarRawError(f"invalid {field}: {value!r}") from exc


def _query_key(row: Mapping[str, str]) -> CalendarQueryKey:
    currency = row["query_currency"].strip().upper()
    if currency not in {"USD", "XAU"}:
        raise CalendarRawError(f"unknown query currency: {currency!r}")
    start = _parse_server_time(
        row["query_start_server"].strip(), "query_start_server"
    )
    end = _parse_server_time(row["query_end_server"].strip(), "query_end_server")
    if end <= start:
        raise CalendarRawError("query_end_server must be after query_start_server")
    return CalendarQueryKey(currency, start, end)


def _load_metadata(path: Path) -> CalendarMetadata:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader, None)
            if header != ["key", "value"]:
                raise CalendarRawError("metadata CSV header must be key,value")
            values: dict[str, str] = {}
            for line_number, row in enumerate(reader, start=2):
                if len(row) != 2:
                    raise CalendarRawError(
                        f"metadata row {line_number} must contain two fields"
                    )
                key, value = (part.strip() for part in row)
                if key in values:
                    raise CalendarRawError(f"duplicate metadata key: {key}")
                values[key] = value
    except OSError as exc:
        raise CalendarRawError(f"cannot read metadata CSV: {path}") from exc

    forbidden = sorted(FORBIDDEN_METADATA_FIELDS.intersection(values))
    if forbidden:
        raise CalendarRawError(f"forbidden metadata fields: {forbidden}")
    missing = sorted(METADATA_FIELDS.difference(values))
    if missing:
        raise CalendarRawError(f"missing metadata fields: {missing}")
    unknown = sorted(set(values).difference(METADATA_FIELDS))
    if unknown:
        raise CalendarRawError(f"unknown metadata fields: {unknown}")
    blank = sorted(key for key, value in values.items() if not value)
    if blank:
        raise CalendarRawError(f"blank metadata fields: {blank}")
    if values["export_status"] != "complete":
        raise CalendarRawError(
            f"export_status must be complete, got {values['export_status']!r}"
        )
    return CalendarMetadata(values)


def _load_events(
    path: Path,
) -> tuple[tuple[CalendarQueryStatus, ...], tuple[RawCalendarEvent, ...]]:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != EVENT_FIELDS:
                raise CalendarRawError(
                    f"event CSV header must be exactly {','.join(EVENT_FIELDS)}"
                )
            query_by_key: dict[CalendarQueryKey, CalendarQueryStatus] = {}
            events: list[RawCalendarEvent] = []
            value_ids: set[int] = set()
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise CalendarRawError(f"event row {line_number} has extra fields")
                cleaned = {key: value.strip() for key, value in row.items()}
                key = _query_key(cleaned)
                count = _parse_int(cleaned["query_count"], "query_count")
                error = _parse_int(cleaned["query_error"], "query_error")
                if count < 0:
                    raise CalendarRawError("query_count must be nonnegative")
                populated = [field for field in EVENT_ONLY_FIELDS if cleaned[field]]
                if not populated:
                    if key in query_by_key:
                        raise CalendarRawError(f"duplicate query status: {key}")
                    query_by_key[key] = CalendarQueryStatus(key, count, error)
                    continue
                missing = [field for field in EVENT_ONLY_FIELDS if not cleaned[field]]
                if missing:
                    if missing == ["source_url"]:
                        raise CalendarRawError(
                            f"blank source_url in event row {line_number}"
                        )
                    raise CalendarRawError(
                        f"incomplete event row {line_number}: missing {missing}"
                    )
                value_id = _parse_int(cleaned["value_id"], "value_id")
                if value_id in value_ids:
                    raise CalendarRawError(f"duplicate value ID: {value_id}")
                value_ids.add(value_id)
                event = RawCalendarEvent(
                    query=key,
                    value_id=value_id,
                    event_id=_parse_int(cleaned["event_id"], "event_id"),
                    time_server=_parse_server_time(
                        cleaned["event_time_server"], "event_time_server"
                    ),
                    time_mode_code=_parse_int(
                        cleaned["event_time_mode_code"], "event_time_mode_code"
                    ),
                    time_mode_name=cleaned["event_time_mode_name"],
                    importance_code=_parse_int(
                        cleaned["event_importance_code"], "event_importance_code"
                    ),
                    importance_name=cleaned["event_importance_name"],
                    country_id=_parse_int(cleaned["country_id"], "country_id"),
                    event_code=cleaned["event_code"],
                    event_name=cleaned["event_name"],
                    source_url=cleaned["source_url"],
                )
                events.append(event)
    except OSError as exc:
        raise CalendarRawError(f"cannot read event CSV: {path}") from exc

    event_counts: dict[CalendarQueryKey, int] = {}
    for event in events:
        event_counts[event.query] = event_counts.get(event.query, 0) + 1
        if event.query not in query_by_key:
            raise CalendarRawError(f"missing query status: {event.query}")
    for key, status in query_by_key.items():
        actual = event_counts.get(key, 0)
        if actual != status.count:
            raise CalendarRawError(
                f"event count differs for {key}: declared {status.count}, actual {actual}"
            )

    queries = tuple(sorted(query_by_key.values(), key=lambda item: item.key))
    ordered_events = tuple(
        sorted(
            events,
            key=lambda item: (
                item.query,
                item.time_server,
                item.event_id,
                item.value_id,
            ),
        )
    )
    return queries, ordered_events


def load_calendar_export(
    events_path: Path | str,
    metadata_path: Path | str,
) -> CalendarExport:
    metadata = _load_metadata(Path(metadata_path))
    queries, events = _load_events(Path(events_path))
    return CalendarExport(queries, events, metadata)
