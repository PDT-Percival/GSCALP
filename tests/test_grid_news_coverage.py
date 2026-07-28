import json
from pathlib import Path

import duckdb
import pandas as pd

from gscalp.grid_config import load_grid_config
from gscalp.grid_news import NewsCode
from gscalp.grid_news_coverage import build_news_coverage_report


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("fixture", frame)
        connection.execute(f"COPY fixture TO '{path.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()


def write_market_with_m5_dates(tmp_path: Path, timestamps: list[str]) -> Path:
    market = tmp_path / "market"
    bars = market / "bars"
    bars.mkdir(parents=True)
    (market / "manifest.json").write_text("{}", encoding="utf-8")
    write_parquet(
        pd.DataFrame(
            {
                "Timestamp": pd.DatetimeIndex(timestamps),
                "BidOpen": [100.0] * len(timestamps),
                "BidHigh": [101.0] * len(timestamps),
                "BidLow": [99.0] * len(timestamps),
                "BidClose": [100.5] * len(timestamps),
            }
        ),
        bars / "M5.parquet",
    )
    return market


def test_coverage_report_counts_clear_missing_and_blocked_sessions(
    tmp_path,
):
    config = load_grid_config(Path("config/grid-v1.0.json"))
    market = write_market_with_m5_dates(
        tmp_path,
        [
            "2020-01-02 13:45:00",
            "2020-01-03 14:30:00",
        ],
    )
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T13:30:00Z,2020-01-02T15:45:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,source clear Jan 2\n"
        "2020-01-03T14:50:00Z,2020-01-03T15:00:00Z,USD,high,"
        "ISM Manufacturing PMI,source blackout Jan 3\n",
        encoding="utf-8",
    )

    report = build_news_coverage_report(config, market, news)

    assert report.total_sessions == 4
    assert report.counts == {
        NewsCode.CLEAR.value: 2,
        NewsCode.MISSING_DATE_CONFIRMATION.value: 1,
        NewsCode.OVERLAPPING_BLACKOUT.value: 1,
    }
    assert report.ready is False
    assert [
        (item.local_date.isoformat(), item.window, item.code)
        for item in report.items
        if item.code != NewsCode.CLEAR.value
    ] == [
        ("2020-01-03", "08:45-09:45", NewsCode.MISSING_DATE_CONFIRMATION.value),
        ("2020-01-03", "09:30-10:30", NewsCode.OVERLAPPING_BLACKOUT.value),
    ]


def test_coverage_report_json_is_auditable(tmp_path):
    config = load_grid_config(Path("config/grid-v1.0.json"))
    market = write_market_with_m5_dates(tmp_path, ["2020-01-02 13:45:00"])
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T13:30:00Z,2020-01-02T15:45:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,source clear Jan 2\n",
        encoding="utf-8",
    )

    payload = build_news_coverage_report(config, market, news).to_json_dict()

    assert json.loads(json.dumps(payload))["ready"] is True
    assert payload["total_sessions"] == 2
    assert payload["counts"] == {NewsCode.CLEAR.value: 2}
    assert payload["items"][0]["source"] == "source clear Jan 2"
