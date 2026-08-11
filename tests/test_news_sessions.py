from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from gscalp.grid_config import load_grid_config
from gscalp.news_sessions import (
    candidate_sessions,
    grid_session_spec,
    pullback_session_spec,
)
from gscalp.pullback_config import load_pullback_config


def write_m5_market(tmp_path: Path, timestamps: list[str]) -> Path:
    market = tmp_path / "market"
    bars = market / "bars"
    bars.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "Timestamp": pd.DatetimeIndex(timestamps),
            "BidOpen": [2000.0] * len(timestamps),
            "BidHigh": [2001.0] * len(timestamps),
            "BidLow": [1999.0] * len(timestamps),
            "BidClose": [2000.5] * len(timestamps),
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


def test_candidate_sessions_match_actual_m5_dates_without_adjacent_days(tmp_path):
    market = write_m5_market(
        tmp_path,
        [
            "2019-12-31 13:45:00",
            "2020-01-02 13:45:00",
            "2026-07-16 12:45:00",
        ],
    )
    config = load_grid_config("config/grid-v1.0.json")

    sessions = candidate_sessions(market, grid_session_spec(config))

    assert {item.local_date for item in sessions} == {date(2020, 1, 2)}
    assert [item.window for item in sessions] == ["08:45-09:45", "09:30-10:30"]


def test_grid_and_pullback_specs_enumerate_their_exact_frozen_windows(tmp_path):
    market = write_m5_market(tmp_path, ["2023-03-10 13:45:00"])

    grid = candidate_sessions(
        market, grid_session_spec(load_grid_config("config/grid-v1.0.json"))
    )
    pullback = candidate_sessions(
        market,
        pullback_session_spec(
            load_pullback_config("config/pullback-v1.1.json")
        ),
    )

    assert [item.version for item in grid] == ["grid-v1.0"] * 2
    assert [item.window for item in grid] == ["08:45-09:45", "09:30-10:30"]
    assert [item.version for item in pullback] == ["pullback-v1.1"] * 3
    assert [item.window for item in pullback] == [
        "08:45-09:45",
        "09:30-10:30",
        "10:00-11:00",
    ]


def test_candidate_session_utc_bounds_follow_new_york_dst(tmp_path):
    market = write_m5_market(
        tmp_path,
        [
            "2023-03-10 13:45:00",
            "2023-03-13 12:45:00",
        ],
    )
    sessions = candidate_sessions(
        market, grid_session_spec(load_grid_config("config/grid-v1.0.json"))
    )

    starts = {
        (item.local_date.isoformat(), item.window): item.start_utc.isoformat()
        for item in sessions
    }
    assert starts[("2023-03-10", "08:45-09:45")] == "2023-03-10T13:45:00+00:00"
    assert starts[("2023-03-13", "08:45-09:45")] == "2023-03-13T12:45:00+00:00"
    assert all(
        item.end_utc - item.start_utc == pd.Timedelta(hours=1)
        for item in sessions
    )
    assert list(sessions) == sorted(
        sessions, key=lambda item: (item.local_date, item.window)
    )
