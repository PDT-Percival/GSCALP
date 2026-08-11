import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from gscalp.news_coverage import build_strategy_news_coverage_report
from gscalp.news_sessions import StrategySessionSpec
from gscalp.pullback_config import load_pullback_config
from gscalp.pullback_news_coverage import (
    build_news_coverage_report as build_pullback_news_coverage_report,
)


def write_market(tmp_path: Path) -> Path:
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


def spec(*windows):
    return StrategySessionSpec(
        version="test-v1",
        windows_ny=tuple(windows),
        first_date=date(2020, 1, 2),
        last_date=date(2020, 1, 2),
    )


def test_blackout_is_complete_source_coverage_but_not_all_sessions_clear(tmp_path):
    market = write_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T13:45:00Z,2020-01-02T14:45:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,source clear\n"
        "2020-01-02T14:50:00Z,2020-01-02T14:50:01Z,USD,high,"
        "ISM Manufacturing PMI,source blackout\n",
        encoding="utf-8",
    )

    report = build_strategy_news_coverage_report(
        spec("08:45-09:45", "09:30-10:30"), market, news
    )

    assert report.strategy_version == "test-v1"
    assert report.total_sessions == 2
    assert report.counts == {"clear": 1, "overlapping_blackout": 1}
    assert report.coverage_complete is True
    assert report.all_sessions_clear is False
    assert report.ready is True
    assert [(item.window, item.code) for item in report.items] == [
        ("08:45-09:45", "clear"),
        ("09:30-10:30", "overlapping_blackout"),
    ]


def test_missing_confirmation_keeps_coverage_incomplete(tmp_path):
    market = write_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n",
        encoding="utf-8",
    )

    report = build_strategy_news_coverage_report(
        spec("08:45-09:45"), market, news
    )

    assert report.counts == {"missing_date_confirmation": 1}
    assert report.coverage_complete is False
    assert report.all_sessions_clear is False
    assert report.ready is False


def test_coverage_json_preserves_status_and_every_audit_item(tmp_path):
    market = write_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T13:45:00Z,2020-01-02T14:45:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,source clear\n",
        encoding="utf-8",
    )

    payload = build_strategy_news_coverage_report(
        spec("08:45-09:45"), market, news
    ).to_json_dict()

    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert payload == {
        "strategy_version": "test-v1",
        "total_sessions": 1,
        "counts": {"clear": 1},
        "coverage_complete": True,
        "all_sessions_clear": True,
        "ready": True,
        "items": [
            {
                "local_date": "2020-01-02",
                "window": "08:45-09:45",
                "session_start_utc": "2020-01-02T13:45:00+00:00",
                "session_end_utc": "2020-01-02T14:45:00+00:00",
                "code": "clear",
                "event_name": "NO_HIGH_IMPACT_EVENTS",
                "source": "source clear",
            }
        ],
    }


def test_pullback_wrapper_uses_all_three_frozen_windows(tmp_path):
    market = write_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T13:45:00Z,2020-01-02T16:00:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,source clear\n",
        encoding="utf-8",
    )

    report = build_pullback_news_coverage_report(
        load_pullback_config("config/pullback-v1.1.json"), market, news
    )

    assert report.strategy_version == "pullback-v1.1"
    assert report.total_sessions == 3
    assert report.counts == {"clear": 3}
    assert report.coverage_complete is True
