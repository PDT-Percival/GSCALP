from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from gscalp.research import (
    TickParquetStore,
    build_liquidity_level_map,
    build_liquidity_levels,
    evaluate_session_bounds,
    load_bar_parquet,
    new_york_session_bounds,
)
from gscalp.models import LevelSide, LiquidityLevel
from gscalp.config import StrategyConfig

from test_config import valid_payload
from test_strategy import bullish_m15, qualifying_long_m5


def test_new_york_session_bounds_follow_dst():
    summer_start, summer_end = new_york_session_bounds(date(2024, 7, 1), "08:45-09:45")
    winter_start, winter_end = new_york_session_bounds(date(2024, 1, 2), "08:45-09:45")

    assert summer_start == pd.Timestamp("2024-07-01 12:45:00+00:00")
    assert summer_end == pd.Timestamp("2024-07-01 13:45:00+00:00")
    assert winter_start == pd.Timestamp("2024-01-02 13:45:00+00:00")
    assert winter_end == pd.Timestamp("2024-01-02 14:45:00+00:00")


def test_liquidity_levels_use_only_completed_prior_sessions():
    index = pd.DatetimeIndex(
        [
            "2024-07-01 10:00:00+00:00",
            "2024-07-01 11:00:00+00:00",
            "2024-07-02 01:00:00+00:00",
            "2024-07-02 07:00:00+00:00",
            "2024-07-02 08:00:00+00:00",
            "2024-07-02 11:55:00+00:00",
            "2024-07-02 12:45:00+00:00",
        ]
    )
    bars = pd.DataFrame(
        {
            "high": [110, 112, 105, 108, 109, 111, 999],
            "low": [90, 88, 95, 94, 93, 92, 0],
        },
        index=index,
    )

    levels = build_liquidity_levels(
        bars, pd.Timestamp("2024-07-02 12:45:00+00:00")
    )
    mapped = {item.name: item for item in levels}

    assert mapped["previous_day_high"].price == 112
    assert mapped["previous_day_low"].price == 88
    assert mapped["asian_high"].price == 108
    assert mapped["asian_low"].price == 94
    assert mapped["london_high"].price == 111
    assert mapped["london_low"].price == 92
    assert mapped["previous_day_high"].side is LevelSide.HIGH
    assert all(item.price != 999 for item in levels)


def test_precomputed_liquidity_map_matches_single_session_calculation():
    index = pd.date_range("2024-06-30", periods=60 * 72, freq="min", tz="UTC")
    bars = pd.DataFrame(
        {
            "high": [value + 2.0 for value in range(len(index))],
            "low": [value - 1.0 for value in range(len(index))],
        },
        index=index,
    )
    session_start = pd.Timestamp("2024-07-01 12:45:00+00:00")

    level_map = build_liquidity_level_map(bars)

    assert level_map[session_start.date()] == build_liquidity_levels(
        bars, session_start
    )


def test_bar_loader_maps_bid_columns_to_canonical_names(tmp_path: Path):
    output = tmp_path / "M5.parquet"
    duckdb.sql(
        """
        COPY (SELECT
          TIMESTAMP '2024-01-02 00:00:00' AS Timestamp,
          1.0 AS BidOpen, 2.0 AS BidHigh, 0.5 AS BidLow, 1.5 AS BidClose,
          1.2 AS AskOpen, 2.2 AS AskHigh, 0.7 AS AskLow, 1.7 AS AskClose,
          10::BIGINT AS TickCount, 0.2 AS MinSpread, 0.3 AS MaxSpread
        ) TO ? (FORMAT PARQUET)
        """,
        params=[str(output)],
    )

    bars = load_bar_parquet(output)

    assert str(bars.index.tz) == "UTC"
    assert bars.iloc[0][["open", "high", "low", "close"]].tolist() == [1.0, 2.0, 0.5, 1.5]
    assert bars.iloc[0]["max_spread"] == 0.3


def test_tick_store_returns_only_requested_utc_interval(tmp_path: Path):
    ticks = tmp_path / "year=2024" / "ticks.parquet"
    ticks.parent.mkdir(parents=True)
    duckdb.sql(
        """
        COPY (SELECT * FROM (VALUES
          (TIMESTAMP '2024-01-02 09:00:00', 100.0, 100.2),
          (TIMESTAMP '2024-01-02 09:30:00', 101.0, 101.2),
          (TIMESTAMP '2024-01-02 10:00:00', 102.0, 102.2)
        ) t(Timestamp, Bid, Ask)) TO ? (FORMAT PARQUET)
        """,
        params=[str(ticks)],
    )
    store = TickParquetStore(tmp_path / "year=*" / "ticks.parquet")

    result = store.slice(
        pd.Timestamp("2024-01-02 09:15:00+00:00"),
        pd.Timestamp("2024-01-02 10:00:00+00:00"),
    )

    assert list(result.index) == [pd.Timestamp("2024-01-02 09:30:00+00:00")]
    assert result.iloc[0].to_dict() == {"bid": 101.0, "ask": 101.2}


def test_session_evaluation_emits_one_deduplicated_qualified_signal():
    m5 = qualifying_long_m5()
    m5["max_spread"] = 0.01
    start = m5.index[14]
    end = start + pd.Timedelta(minutes=60)
    levels = (
        LiquidityLevel("session_low", 100.0, LevelSide.LOW),
        LiquidityLevel("session_high", 102.0, LevelSide.HIGH),
    )

    result = evaluate_session_bounds(
        m5,
        bullish_m15(),
        levels,
        start,
        end,
        StrategyConfig(**valid_payload()),
        window="fixture",
    )

    assert len(result.decisions) == 3
    assert len(result.qualified_signals) == 1
    assert result.qualified_signals[0].signal_time == m5.index[16]
