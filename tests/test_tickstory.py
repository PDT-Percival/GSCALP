from pathlib import Path

import duckdb
import pytest

from gscalp.tickstory import (
    aggregate_tick_parquet_to_bars,
    convert_tick_csv_to_parquet,
    discover_annual_tick_files,
    validate_non_overlapping_boundaries,
)


HEADER = "Timestamp,Bid,Ask,BidVolume,AskVolume,Spread\n"


def write_ticks(path: Path, rows: list[str]) -> None:
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")


def test_discovery_ignores_partial_and_misnamed_files(tmp_path: Path):
    write_ticks(
        tmp_path / "XAUUSD_ticks_2020.csv",
        ["2020-01-02 00:00:00.001,1500,1500.2,1,1,0.2"],
    )
    write_ticks(
        tmp_path / "xXAUUSD_ticks_2021.csv",
        ["2021-01-04 00:00:00.001,1900,1900.2,1,1,0.2"],
    )
    write_ticks(
        tmp_path / "XAUUSD_ticks_sample.csv",
        ["2020-01-02 00:00:00.001,1500,1500.2,1,1,0.2"],
    )

    files = discover_annual_tick_files(tmp_path)

    assert [(item.year, item.path.name) for item in files] == [
        (2020, "XAUUSD_ticks_2020.csv")
    ]


def test_boundary_validation_rejects_overlapping_annual_files(tmp_path: Path):
    write_ticks(
        tmp_path / "XAUUSD_ticks_2020.csv",
        [
            "2020-01-02 00:00:00.001,1500,1500.2,1,1,0.2",
            "2021-01-01 00:00:00.001,1800,1800.2,1,1,0.2",
        ],
    )
    write_ticks(
        tmp_path / "XAUUSD_ticks_2021.csv",
        ["2021-01-01 00:00:00.001,1800,1800.2,1,1,0.2"],
    )

    with pytest.raises(ValueError, match="overlap"):
        validate_non_overlapping_boundaries(discover_annual_tick_files(tmp_path))


def test_conversion_excludes_declared_dates_and_preserves_quotes(tmp_path: Path):
    source = tmp_path / "XAUUSD_ticks_2020.csv"
    output = tmp_path / "year=2020" / "ticks.parquet"
    write_ticks(
        source,
        [
            "2020-01-02 00:00:00.001,1500,1500.2,1,2,0.2",
            "2020-12-31 00:00:00.001,1800,1800.3,3,4,0.3",
        ],
    )

    result = convert_tick_csv_to_parquet(
        source, output, excluded_dates={"2020-12-31"}
    )

    assert result.rows_written == 1
    row = duckdb.sql(
        f"SELECT Timestamp, Bid, Ask, Spread FROM read_parquet('{output.as_posix()}')"
    ).fetchone()
    assert str(row[0]) == "2020-01-02 00:00:00.001000"
    assert row[1:] == (1500.0, 1500.2, 0.2)


def test_conversion_rejects_incorrect_spread(tmp_path: Path):
    source = tmp_path / "XAUUSD_ticks_2020.csv"
    write_ticks(
        source,
        ["2020-01-02 00:00:00.001,1500,1500.2,1,1,0.9"],
    )

    with pytest.raises(ValueError, match="spread mismatch"):
        convert_tick_csv_to_parquet(source, tmp_path / "ticks.parquet")


def test_tick_aggregation_builds_bid_and_ask_ohlc(tmp_path: Path):
    source = tmp_path / "XAUUSD_ticks_2020.csv"
    ticks = tmp_path / "ticks.parquet"
    bars = tmp_path / "m1.parquet"
    write_ticks(
        source,
        [
            "2020-01-02 00:00:00.001,1500.0,1500.2,1,2,0.2",
            "2020-01-02 00:00:30.001,1501.0,1501.3,1,2,0.3",
            "2020-01-02 00:01:00.001,1500.5,1500.7,1,2,0.2",
        ],
    )
    convert_tick_csv_to_parquet(source, ticks)

    result = aggregate_tick_parquet_to_bars([ticks], bars, minutes=1)

    assert result.rows_written == 2
    first = duckdb.sql(
        f"SELECT * FROM read_parquet('{bars.as_posix()}') ORDER BY Timestamp LIMIT 1"
    ).fetchone()
    assert str(first[0]) == "2020-01-02 00:00:00"
    assert first[1:5] == (1500.0, 1501.0, 1500.0, 1501.0)
    assert first[5:9] == (1500.2, 1501.3, 1500.2, 1501.3)
    assert first[9:] == (2, 0.2, 0.3)


def test_tick_aggregation_rejects_unsupported_timeframe(tmp_path: Path):
    with pytest.raises(ValueError, match="supported timeframe"):
        aggregate_tick_parquet_to_bars([], tmp_path / "bars.parquet", minutes=7)
