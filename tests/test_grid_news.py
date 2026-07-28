from pathlib import Path

import pandas as pd

from gscalp.grid_news import NewsCode, news_gate


def write_news(path: Path, rows: str = "") -> None:
    path.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        + rows,
        encoding="utf-8",
    )


def test_empty_news_file_is_not_date_confirmation(tmp_path):
    path = tmp_path / "news.csv"
    write_news(path)

    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )

    assert result.allowed is False
    assert result.code is NewsCode.MISSING_DATE_CONFIRMATION
    assert result.matching_rows == ()


def test_explicit_source_backed_clear_day_allows_session(tmp_path):
    path = tmp_path / "news.csv"
    write_news(
        path,
        "2026-07-28 00:00:00+00:00,2026-07-29 00:00:00+00:00,ALL,none,NO_HIGH_IMPACT_EVENTS,Trading Economics export 2026-07-28\n",
    )

    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )

    assert result.allowed is True
    assert result.code is NewsCode.CLEAR
    assert len(result.matching_rows) == 1
    assert result.matching_rows[0]["event_name"] == "NO_HIGH_IMPACT_EVENTS"


def test_overlapping_high_impact_usd_event_blocks_session(tmp_path):
    path = tmp_path / "news.csv"
    write_news(
        path,
        "2026-07-28 00:00:00+00:00,2026-07-29 00:00:00+00:00,ALL,none,NO_HIGH_IMPACT_EVENTS,Trading Economics export 2026-07-28\n"
        "2026-07-28 13:45:00+00:00,2026-07-28 14:00:00+00:00,USD,high,FOMC statement,Trading Economics event 123\n",
    )

    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )

    assert result.allowed is False
    assert result.code is NewsCode.OVERLAPPING_BLACKOUT
    assert len(result.matching_rows) == 1
    assert result.matching_rows[0]["event_name"] == "FOMC statement"


def test_stale_clear_day_does_not_confirm_today(tmp_path):
    path = tmp_path / "news.csv"
    write_news(
        path,
        "2026-07-27 00:00:00+00:00,2026-07-28 00:00:00+00:00,ALL,none,NO_HIGH_IMPACT_EVENTS,Trading Economics export 2026-07-27\n",
    )

    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )

    assert result.allowed is False
    assert result.code is NewsCode.MISSING_DATE_CONFIRMATION
    assert result.matching_rows == ()


def test_blackout_starting_previous_utc_date_still_blocks_session(tmp_path):
    path = tmp_path / "news.csv"
    write_news(
        path,
        "2026-07-28 00:00:00+00:00,2026-07-29 00:00:00+00:00,ALL,none,NO_HIGH_IMPACT_EVENTS,Trading Economics export 2026-07-28\n"
        "2026-07-27 23:55:00+00:00,2026-07-28 13:40:00+00:00,XAU,high,Gold liquidity event,Trading Economics event 456\n",
    )

    result = news_gate(
        path,
        pd.Timestamp("2026-07-28 13:30:00+00:00"),
        pd.Timestamp("2026-07-28 14:30:00+00:00"),
        pd.Timedelta(minutes=15),
    )

    assert result.allowed is False
    assert result.code is NewsCode.OVERLAPPING_BLACKOUT
    assert len(result.matching_rows) == 1
    assert result.matching_rows[0]["event_name"] == "Gold liquidity event"
