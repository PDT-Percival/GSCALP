import csv
from datetime import datetime
from pathlib import Path

import pytest

from gscalp.mt5_calendar_raw import (
    CalendarQueryKey,
    CalendarRawError,
    load_calendar_export,
)


EVENT_FIELDS = [
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
]

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


def query_row(**changes):
    row = {
        "query_currency": "USD",
        "query_start_server": "2020.01.01 00:00:00",
        "query_end_server": "2020.02.01 00:00:00",
        "query_count": "1",
        "query_error": "0",
        "value_id": "",
        "event_id": "",
        "event_time_server": "",
        "event_time_mode_code": "",
        "event_time_mode_name": "",
        "event_importance_code": "",
        "event_importance_name": "",
        "country_id": "",
        "event_code": "",
        "event_name": "",
        "source_url": "",
    }
    row.update(changes)
    return row


def event_row(**changes):
    row = query_row(
        value_id="54215",
        event_id="319281",
        event_time_server="2020.01.03 15:00:00",
        event_time_mode_code="0",
        event_time_mode_name="CALENDAR_TIMEMODE_DATETIME",
        event_importance_code="3",
        event_importance_name="CALENDAR_IMPORTANCE_HIGH",
        country_id="840",
        event_code="USANONFARM",
        event_name="Non Farm Payrolls",
        source_url="https://www.bls.gov/",
    )
    row.update(changes)
    return row


def write_csv(path: Path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_export(tmp_path, *, rows=None, metadata=None, fields=None):
    events_path = tmp_path / "events.csv"
    metadata_path = tmp_path / "metadata.csv"
    write_csv(
        events_path,
        fields or EVENT_FIELDS,
        rows if rows is not None else [query_row(), event_row()],
    )
    write_csv(
        metadata_path,
        ["key", "value"],
        [
            {"key": key, "value": value}
            for key, value in (metadata or METADATA).items()
        ],
    )
    return events_path, metadata_path


def test_load_calendar_export_parses_query_event_and_safe_metadata(tmp_path):
    events_path, metadata_path = write_export(tmp_path)

    result = load_calendar_export(events_path, metadata_path)

    key = CalendarQueryKey(
        currency="USD",
        start_server=datetime(2020, 1, 1),
        end_server=datetime(2020, 2, 1),
    )
    assert result.queries[0].key == key
    assert result.queries[0].count == 1
    assert result.queries[0].error == 0
    assert result.events[0].query == key
    assert result.events[0].value_id == 54215
    assert result.events[0].event_id == 319281
    assert result.events[0].time_server == datetime(2020, 1, 3, 15)
    assert result.events[0].time_server.tzinfo is None
    assert result.events[0].importance_name == "CALENDAR_IMPORTANCE_HIGH"
    assert result.events[0].source_url == "https://www.bls.gov/"
    assert result.metadata.values == METADATA
    assert not any(
        key in result.metadata.values
        for key in {"account_login", "password", "balance", "equity", "name"}
    )


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([query_row(), query_row(), event_row()], "duplicate query status"),
        (
            [query_row(query_count="2"), event_row(), event_row()],
            "duplicate value ID",
        ),
        ([query_row(query_count="2"), event_row()], "event count differs"),
        ([query_row(), event_row(source_url="")], "blank source_url"),
        (
            [
                query_row(query_currency="EUR"),
                event_row(query_currency="EUR"),
            ],
            "unknown query currency",
        ),
        (
            [query_row(), event_row(event_time_server="2020-01-03T15:00:00Z")],
            "invalid event_time_server",
        ),
        ([event_row()], "missing query status"),
        (
            [query_row(value_id="unexpected"), event_row()],
            "incomplete event row",
        ),
    ],
)
def test_load_calendar_export_rejects_malformed_event_contract(
    tmp_path, rows, message
):
    events_path, metadata_path = write_export(tmp_path, rows=rows)

    with pytest.raises(CalendarRawError, match=message):
        load_calendar_export(events_path, metadata_path)


def test_load_calendar_export_requires_exact_event_header(tmp_path):
    fields = [field for field in EVENT_FIELDS if field != "source_url"]
    events_path, metadata_path = write_export(
        tmp_path,
        fields=fields,
        rows=[{key: value for key, value in query_row().items() if key in fields}],
    )

    with pytest.raises(CalendarRawError, match="event CSV header"):
        load_calendar_export(events_path, metadata_path)


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({**METADATA, "export_status": "started"}, "export_status"),
        ({key: value for key, value in METADATA.items() if key != "terminal_build"}, "missing metadata"),
        ({**METADATA, "account_login": "123456"}, "forbidden metadata"),
        ({**METADATA, "unknown": "value"}, "unknown metadata"),
        ({**METADATA, "terminal_company": ""}, "blank metadata"),
    ],
)
def test_load_calendar_export_rejects_unsafe_or_incomplete_metadata(
    tmp_path, metadata, message
):
    events_path, metadata_path = write_export(tmp_path, metadata=metadata)

    with pytest.raises(CalendarRawError, match=message):
        load_calendar_export(events_path, metadata_path)


def test_load_calendar_export_rejects_duplicate_metadata_key(tmp_path):
    events_path, metadata_path = write_export(tmp_path)
    with metadata_path.open("a", encoding="utf-8", newline="") as stream:
        stream.write("terminal_build,9999\n")

    with pytest.raises(CalendarRawError, match="duplicate metadata key"):
        load_calendar_export(events_path, metadata_path)
