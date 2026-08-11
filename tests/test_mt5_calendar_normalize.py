from datetime import datetime

import pandas as pd
import pytest

from gscalp.mt5_calendar_normalize import (
    CalendarNormalizationError,
    expected_monthly_queries,
    normalize_calendar_news,
    validate_complete_export,
)
from gscalp.mt5_calendar_raw import (
    CalendarExport,
    CalendarMetadata,
    CalendarQueryKey,
    CalendarQueryStatus,
    RawCalendarEvent,
)
from gscalp.news_sessions import CandidateSession


RAW_SHA256 = "a" * 64

METADATA = {
    "script_version": "mt5-calendar-v1",
    "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
    "terminal_build": "5440",
    "terminal_company": "MetaQuotes Ltd.",
    "account_server": "FBS-Demo",
    "account_trade_mode": "0",
    "account_margin_mode": "2",
    "requested_from_server": "2020.01.01 00:00:00",
    "requested_to_server": "2026.08.01 00:00:00",
    "generated_at_server": "2026.08.11 19:00:00",
    "current_server_time": "2026.08.11 19:00:00",
    "current_gmt_time": "2026.08.11 16:00:00",
    "calendar_currencies": "EUR;USD",
    "export_status": "complete",
}


def query_keys():
    keys = []
    start = datetime(2020, 1, 1)
    limit = datetime(2026, 8, 1)
    while start < limit:
        end = (
            datetime(start.year + 1, 1, 1)
            if start.month == 12
            else datetime(start.year, start.month + 1, 1)
        )
        for currency in ("USD", "XAU"):
            keys.append(CalendarQueryKey(currency, start, end))
        start = end
    assert len(keys) == 158
    return tuple(keys)


def key_for(currency, year, month):
    return next(
        key
        for key in query_keys()
        if key.currency == currency
        and key.start_server == datetime(year, month, 1)
    )


def raw_event(
    *,
    value_id=1,
    event_id=1001,
    currency="USD",
    time_server=datetime(2020, 1, 3, 15),
    time_mode_code=0,
    time_mode_name="CALENDAR_TIMEMODE_DATETIME",
    importance_code=3,
    importance_name="CALENDAR_IMPORTANCE_HIGH",
    event_name="Non Farm Payrolls",
    source_url="https://www.bls.gov/",
):
    return RawCalendarEvent(
        query=key_for(currency, time_server.year, time_server.month),
        value_id=value_id,
        event_id=event_id,
        time_server=time_server,
        time_mode_code=time_mode_code,
        time_mode_name=time_mode_name,
        importance_code=importance_code,
        importance_name=importance_name,
        country_id=840,
        event_code=f"EVENT{event_id}",
        event_name=event_name,
        source_url=source_url,
    )


def complete_export(*events, metadata=None, query_overrides=None):
    event_counts = {}
    for event in events:
        event_counts[event.query] = event_counts.get(event.query, 0) + 1
    overrides = query_overrides or {}
    queries = tuple(
        overrides.get(
            key,
            CalendarQueryStatus(
                key=key,
                count=event_counts.get(key, 0),
                error=0,
            ),
        )
        for key in query_keys()
    )
    return CalendarExport(
        queries=queries,
        events=tuple(events),
        metadata=CalendarMetadata(metadata or METADATA),
    )


def session(local_date, window, start, end, version="grid-v1.0"):
    return CandidateSession(
        version=version,
        local_date=pd.Timestamp(local_date).date(),
        window=window,
        start_utc=pd.Timestamp(start),
        end_utc=pd.Timestamp(end),
    )


def test_expected_monthly_queries_are_month_major_and_currency_minor():
    assert expected_monthly_queries(
        datetime(2020, 1, 1), datetime(2020, 3, 1)
    ) == (
        CalendarQueryKey("USD", datetime(2020, 1, 1), datetime(2020, 2, 1)),
        CalendarQueryKey("XAU", datetime(2020, 1, 1), datetime(2020, 2, 1)),
        CalendarQueryKey("USD", datetime(2020, 2, 1), datetime(2020, 3, 1)),
        CalendarQueryKey("XAU", datetime(2020, 2, 1), datetime(2020, 3, 1)),
    )


def test_validate_complete_export_accepts_exact_158_query_lattice():
    export = complete_export()

    validate_complete_export(export)

    assert len(export.queries) == 158


def test_validate_complete_export_rejects_a_missing_xau_month():
    export = complete_export()
    export = CalendarExport(
        queries=tuple(
            query
            for query in export.queries
            if query.key != key_for("XAU", 2023, 4)
        ),
        events=export.events,
        metadata=export.metadata,
    )

    with pytest.raises(CalendarNormalizationError, match="missing queries"):
        validate_complete_export(export)


def test_validate_complete_export_rejects_query_error_and_count_mismatch():
    key = key_for("USD", 2024, 1)
    bad_error = complete_export(
        query_overrides={key: CalendarQueryStatus(key, count=0, error=5401)}
    )
    with pytest.raises(CalendarNormalizationError, match="query error"):
        validate_complete_export(bad_error)

    bad_count = complete_export(
        query_overrides={key: CalendarQueryStatus(key, count=1, error=0)}
    )
    with pytest.raises(CalendarNormalizationError, match="event count"):
        validate_complete_export(bad_count)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("terminal_path", r"C:\Program Files\Other\terminal64.exe", "terminal_path"),
        ("account_server", "FBS-Real", "account_server"),
        ("account_trade_mode", "1", "account_trade_mode"),
        ("account_margin_mode", "0", "account_margin_mode"),
        ("requested_from_server", "2020.01.02 00:00:00", "requested_from_server"),
        ("requested_to_server", "2026.07.16 00:00:00", "requested_to_server"),
    ],
)
def test_validate_complete_export_rejects_environment_or_range_drift(
    field, value, message
):
    export = complete_export(metadata={**METADATA, field: value})

    with pytest.raises(CalendarNormalizationError, match=message):
        validate_complete_export(export)


def test_validate_complete_export_rejects_event_outside_parent_month():
    event = raw_event(time_server=datetime(2020, 2, 1))
    event = RawCalendarEvent(
        query=key_for("USD", 2020, 1),
        value_id=event.value_id,
        event_id=event.event_id,
        time_server=event.time_server,
        time_mode_code=event.time_mode_code,
        time_mode_name=event.time_mode_name,
        importance_code=event.importance_code,
        importance_name=event.importance_name,
        country_id=event.country_id,
        event_code=event.event_code,
        event_name=event.event_name,
        source_url=event.source_url,
    )

    with pytest.raises(CalendarNormalizationError, match="outside query interval"):
        validate_complete_export(complete_export(event))


def test_exact_high_event_blocks_one_session_and_other_session_gets_clear_row():
    event = raw_event()
    blocked = session(
        "2020-01-03",
        "08:00-09:00",
        "2020-01-03T13:00:00Z",
        "2020-01-03T14:00:00Z",
    )
    clear = session(
        "2020-01-03",
        "09:00-10:00",
        "2020-01-03T14:00:00Z",
        "2020-01-03T15:00:00Z",
    )

    rows = normalize_calendar_news(
        complete_export(event), (blocked, clear), RAW_SHA256
    )

    event_row = next(row for row in rows if row.impact == "high")
    clear_row = next(row for row in rows if row.impact == "none")
    assert event_row.event_start_utc == pd.Timestamp("2020-01-03T13:00:00Z")
    assert event_row.event_end_utc == pd.Timestamp("2020-01-03T13:00:01Z")
    assert event_row.currency == "USD"
    assert event_row.source == (
        f"MT5 Calendar event 1001; https://www.bls.gov/; raw={RAW_SHA256}"
    )
    assert clear_row.event_start_utc == clear.start_utc
    assert clear_row.event_end_utc == clear.end_utc
    assert clear_row.currency == "ALL"
    assert clear_row.event_name == "NO_HIGH_IMPACT_EVENTS"
    assert clear_row.source == (
        f"MT5 Calendar complete USD+XAU queries; raw={RAW_SHA256}"
    )


@pytest.mark.parametrize(
    ("time_mode_code", "time_mode_name"),
    [
        (1, "CALENDAR_TIMEMODE_DATE"),
        (2, "CALENDAR_TIMEMODE_NOTIME"),
        (3, "CALENDAR_TIMEMODE_TENTATIVE"),
    ],
)
def test_non_exact_high_events_block_the_complete_fbs_server_day(
    time_mode_code, time_mode_name
):
    event = raw_event(
        time_server=datetime(2026, 3, 29),
        time_mode_code=time_mode_code,
        time_mode_name=time_mode_name,
    )

    rows = normalize_calendar_news(complete_export(event), (), RAW_SHA256)

    assert len(rows) == 1
    assert rows[0].event_start_utc == pd.Timestamp("2026-03-28T22:00:00Z")
    assert rows[0].event_end_utc == pd.Timestamp("2026-03-29T21:00:00Z")
    assert rows[0].event_end_utc - rows[0].event_start_utc == pd.Timedelta(
        hours=23
    )


def test_moderate_event_is_omitted_but_session_is_explicitly_clear():
    event = raw_event(
        importance_code=2,
        importance_name="CALENDAR_IMPORTANCE_MODERATE",
    )
    candidate = session(
        "2020-01-03",
        "08:00-09:00",
        "2020-01-03T13:00:00Z",
        "2020-01-03T14:00:00Z",
    )

    rows = normalize_calendar_news(
        complete_export(event), (candidate,), RAW_SHA256
    )

    assert [(row.impact, row.event_name) for row in rows] == [
        ("none", "NO_HIGH_IMPACT_EVENTS")
    ]


def test_normalize_rejects_enum_mismatch_ambiguous_time_and_bad_hash():
    mismatch = raw_event(
        importance_code=2,
        importance_name="CALENDAR_IMPORTANCE_HIGH",
    )
    with pytest.raises(CalendarNormalizationError, match="importance code/name"):
        normalize_calendar_news(complete_export(mismatch), (), RAW_SHA256)

    ambiguous = raw_event(time_server=datetime(2025, 10, 26, 3, 30))
    with pytest.raises(CalendarNormalizationError, match="ambiguous FBS server time"):
        normalize_calendar_news(complete_export(ambiguous), (), RAW_SHA256)

    with pytest.raises(CalendarNormalizationError, match="raw SHA-256"):
        normalize_calendar_news(complete_export(), (), "not-a-hash")
