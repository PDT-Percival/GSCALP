import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from gscalp.mt5_calendar_normalize import CalendarNormalizationError
from gscalp.mt5_calendar_pipeline import (
    CalendarImportRequest,
    run_mt5_calendar_import,
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


def month_ranges():
    values = []
    start = datetime(2020, 1, 1)
    limit = datetime(2026, 8, 1)
    while start < limit:
        end = (
            datetime(start.year + 1, 1, 1)
            if start.month == 12
            else datetime(start.year, start.month + 1, 1)
        )
        values.append((start, end))
        start = end
    assert len(values) == 79
    return values


def query_row(currency, start, end, count):
    return {
        "query_currency": currency,
        "query_start_server": start.strftime("%Y.%m.%d %H:%M:%S"),
        "query_end_server": end.strftime("%Y.%m.%d %H:%M:%S"),
        "query_count": str(count),
        "query_error": "0",
        **{field: "" for field in EVENT_FIELDS[5:]},
    }


def event_row(start, end):
    return {
        **query_row("USD", start, end, 1),
        "value_id": "54215",
        "event_id": "319281",
        "event_time_server": "2020.01.02 16:45:00",
        "event_time_mode_code": "0",
        "event_time_mode_name": "CALENDAR_TIMEMODE_DATETIME",
        "event_importance_code": "3",
        "event_importance_name": "CALENDAR_IMPORTANCE_HIGH",
        "country_id": "840",
        "event_code": "USAISM",
        "event_name": "ISM Manufacturing PMI",
        "source_url": "https://www.ismworld.org/",
    }


def write_raw_export(tmp_path, *, omit_last_xau=False):
    events_path = tmp_path / "mt5_calendar_events.csv"
    rows = []
    for index, (start, end) in enumerate(month_ranges()):
        rows.append(query_row("USD", start, end, 1 if index == 0 else 0))
        if index == 0:
            rows.append(event_row(start, end))
        if not (omit_last_xau and index == 78):
            rows.append(query_row("XAU", start, end, 0))
    with events_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=EVENT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    metadata_path = tmp_path / "mt5_calendar_metadata.csv"
    with metadata_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["key", "value"], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(
            {"key": key, "value": value} for key, value in METADATA.items()
        )
    return events_path, metadata_path


def write_market(tmp_path):
    market = tmp_path / "market"
    bars = market / "bars"
    bars.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "Timestamp": pd.DatetimeIndex(["2020-01-02 13:45:00"]),
            "BidOpen": [2000.0],
            "BidHigh": [2001.0],
            "BidLow": [1999.0],
            "BidClose": [2000.5],
        }
    )
    connection = duckdb.connect()
    try:
        connection.register("fixture", frame)
        connection.execute(
            f"COPY fixture TO '{(bars / 'M5.parquet').as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()
    return market


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request(tmp_path, *, omit_last_xau=False, mq5_exists=True):
    raw_events, raw_metadata = write_raw_export(
        tmp_path, omit_last_xau=omit_last_xau
    )
    mq5 = tmp_path / "GSCALP_NewsExport.mq5"
    if mq5_exists:
        mq5.write_text("#property strict\nvoid OnStart() {}\n", encoding="utf-8")
    return CalendarImportRequest(
        raw_events=raw_events,
        raw_metadata=raw_metadata,
        mq5_source=mq5,
        market_root=write_market(tmp_path),
        news_output=tmp_path / "data" / "news_blackouts.csv",
        artifact_root=tmp_path / "artifacts" / "news" / "mt5-calendar",
        grid_config=Path("config/grid-v1.0.json"),
        pullback_config=Path("config/pullback-v1.1.json"),
        git_commit="0123456789abcdef",
    )


def test_import_pipeline_writes_hashed_complete_artifacts_and_news_last(tmp_path):
    import_request = request(tmp_path)

    result = run_mt5_calendar_import(import_request)

    assert result.status == "complete"
    assert result.application_can_trade is False
    assert result.grid_coverage.coverage_complete is True
    assert result.pullback_coverage.coverage_complete is True
    assert result.grid_coverage.counts == {
        "clear": 1,
        "overlapping_blackout": 1,
    }
    assert result.pullback_coverage.counts == {
        "clear": 2,
        "overlapping_blackout": 1,
    }
    assert result.news_path.read_text(encoding="utf-8").splitlines()[0] == (
        "event_start_utc,event_end_utc,currency,impact,event_name,source"
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format_version"] == "mt5-calendar-manifest-v1"
    assert manifest["status"] == "complete"
    assert manifest["retrieved_at_utc"] == "2026-08-11T16:00:00+00:00"
    assert manifest["account"] == {
        "server": "FBS-Demo",
        "trade_mode": 0,
        "margin_mode": 2,
    }
    assert manifest["query_counts"] == {
        "total": 158,
        "USD": 79,
        "XAU": 79,
        "events": 1,
    }
    assert manifest["application_can_trade"] is False
    assert "login" not in json.dumps(manifest).lower()

    hashes = manifest["hashes"]
    assert hashes["raw_events_sha256"] == sha256(import_request.raw_events)
    assert hashes["raw_metadata_sha256"] == sha256(import_request.raw_metadata)
    assert hashes["mq5_source_sha256"] == sha256(import_request.mq5_source)
    assert hashes["normalized_news_sha256"] == sha256(result.news_path)
    assert result.raw_sha256 == hashes["raw_events_sha256"]
    assert result.normalized_sha256 == hashes["normalized_news_sha256"]
    assert hashes["grid_coverage_sha256"] == sha256(
        import_request.artifact_root / "grid-v1.0-coverage.json"
    )
    assert hashes["pullback_coverage_sha256"] == sha256(
        import_request.artifact_root / "pullback-v1.1-coverage.json"
    )
    assert json.loads(json.dumps(manifest, allow_nan=False)) == manifest


def test_incomplete_export_preserves_existing_canonical_news(tmp_path):
    import_request = request(tmp_path, omit_last_xau=True)
    import_request.news_output.parent.mkdir(parents=True)
    original = b"known-good-news\n"
    import_request.news_output.write_bytes(original)

    with pytest.raises(CalendarNormalizationError, match="missing queries"):
        run_mt5_calendar_import(import_request)

    assert import_request.news_output.read_bytes() == original
    assert not (import_request.artifact_root / "manifest.json").exists()


def test_missing_mql5_source_preserves_existing_canonical_news(tmp_path):
    import_request = request(tmp_path, mq5_exists=False)
    import_request.news_output.parent.mkdir(parents=True)
    original = b"known-good-news\n"
    import_request.news_output.write_bytes(original)

    with pytest.raises(FileNotFoundError, match="MQL5 source"):
        run_mt5_calendar_import(import_request)

    assert import_request.news_output.read_bytes() == original
