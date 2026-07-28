from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import duckdb


EXPECTED_HEADER = "Timestamp,Bid,Ask,BidVolume,AskVolume,Spread"
ANNUAL_PATTERN = re.compile(r"^XAUUSD_ticks_(20\d{2})\.csv$")


@dataclass(frozen=True, slots=True)
class TickFile:
    path: Path
    year: int
    first_timestamp: datetime
    last_timestamp: datetime


@dataclass(frozen=True, slots=True)
class ConversionResult:
    source: Path
    output: Path
    rows_written: int


@dataclass(frozen=True, slots=True)
class AggregationResult:
    output: Path
    minutes: int
    rows_written: int


def _parse_timestamp(line: str) -> datetime:
    timestamp = line.split(",", maxsplit=1)[0]
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f").replace(
        tzinfo=timezone.utc
    )


def _last_nonempty_line(path: Path) -> str:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell() - 1
        while position >= 0:
            stream.seek(position)
            if stream.read(1) not in (b"\n", b"\r"):
                break
            position -= 1
        end = position + 1
        while position >= 0:
            stream.seek(position)
            if stream.read(1) == b"\n":
                position += 1
                break
            position -= 1
        stream.seek(max(position, 0))
        return stream.read(end - max(position, 0)).decode("utf-8")


def discover_annual_tick_files(folder: Path | str) -> list[TickFile]:
    root = Path(folder)
    results: list[TickFile] = []
    for path in sorted(root.iterdir()):
        match = ANNUAL_PATTERN.fullmatch(path.name)
        if match is None or not path.is_file():
            continue
        with path.open("r", encoding="utf-8", newline="") as stream:
            header = stream.readline().strip()
            first = stream.readline().strip()
        if header != EXPECTED_HEADER:
            raise ValueError(f"unexpected Tickstory header in {path.name}: {header}")
        if not first:
            raise ValueError(f"Tickstory file has no data rows: {path.name}")
        last = _last_nonempty_line(path)
        results.append(
            TickFile(
                path=path,
                year=int(match.group(1)),
                first_timestamp=_parse_timestamp(first),
                last_timestamp=_parse_timestamp(last),
            )
        )
    return results


def validate_non_overlapping_boundaries(files: Iterable[TickFile]) -> None:
    ordered = sorted(files, key=lambda item: item.first_timestamp)
    for previous, current in zip(ordered, ordered[1:]):
        if current.first_timestamp <= previous.last_timestamp:
            raise ValueError(
                "Tickstory annual file overlap: "
                f"{previous.path.name} ends {previous.last_timestamp.isoformat()} and "
                f"{current.path.name} starts {current.first_timestamp.isoformat()}"
            )


def _quoted_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def convert_tick_csv_to_parquet(
    source: Path | str,
    output: Path | str,
    *,
    excluded_dates: set[str] | None = None,
) -> ConversionResult:
    source_path = Path(source)
    output_path = Path(output)
    excluded_dates = excluded_dates or set()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_sql = _quoted_path(source_path)
    output_sql = _quoted_path(output_path)
    relation = (
        f"read_csv('{source_sql}', header=true, strict_mode=true, columns={{"
        "'Timestamp':'TIMESTAMP','Bid':'DOUBLE','Ask':'DOUBLE',"
        "'BidVolume':'DOUBLE','AskVolume':'DOUBLE','Spread':'DOUBLE'})"
    )
    connection = duckdb.connect()
    invalid = connection.execute(
        f"""
        SELECT
          count_if(Bid > Ask) AS crossed,
          count_if(Bid <= 0 OR Ask <= 0) AS nonpositive,
          count_if(BidVolume < 0 OR AskVolume < 0) AS negative_volume,
          count_if(abs(Spread - (Ask - Bid)) > 1e-9) AS spread_mismatch
        FROM {relation}
        """
    ).fetchone()
    if any(invalid):
        labels = ("crossed quote", "nonpositive price", "negative volume", "spread mismatch")
        failures = [f"{label}: {count}" for label, count in zip(labels, invalid) if count]
        raise ValueError("; ".join(failures))
    date_filter = ""
    if excluded_dates:
        values = ", ".join(f"DATE '{value}'" for value in sorted(excluded_dates))
        date_filter = f"WHERE CAST(Timestamp AS DATE) NOT IN ({values})"
    connection.execute(
        f"""
        COPY (
          SELECT Timestamp, Bid, Ask, BidVolume, AskVolume, Spread
          FROM {relation}
          {date_filter}
          ORDER BY Timestamp
        ) TO '{output_sql}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """
    )
    rows_written = connection.execute(
        f"SELECT count(*) FROM read_parquet('{output_sql}')"
    ).fetchone()[0]
    connection.close()
    return ConversionResult(source_path, output_path, int(rows_written))


def aggregate_tick_parquet_to_bars(
    inputs: Iterable[Path | str],
    output: Path | str,
    *,
    minutes: int,
) -> AggregationResult:
    if minutes not in {1, 5, 15, 60}:
        raise ValueError("supported timeframe minutes are 1, 5, 15, and 60")
    input_paths = [Path(item) for item in inputs]
    if not input_paths:
        raise ValueError("at least one tick parquet input is required")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_list = ", ".join(f"'{_quoted_path(path)}'" for path in input_paths)
    output_sql = _quoted_path(output_path)
    interval = f"{minutes} minutes"
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
          SELECT
            time_bucket(INTERVAL '{interval}', Timestamp) AS Timestamp,
            arg_min(Bid, Timestamp) AS BidOpen,
            max(Bid) AS BidHigh,
            min(Bid) AS BidLow,
            arg_max(Bid, Timestamp) AS BidClose,
            arg_min(Ask, Timestamp) AS AskOpen,
            max(Ask) AS AskHigh,
            min(Ask) AS AskLow,
            arg_max(Ask, Timestamp) AS AskClose,
            count(*)::BIGINT AS TickCount,
            min(Spread) AS MinSpread,
            max(Spread) AS MaxSpread
          FROM read_parquet([{source_list}])
          GROUP BY 1
          ORDER BY 1
        ) TO '{output_sql}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """
    )
    rows_written = connection.execute(
        f"SELECT count(*) FROM read_parquet('{output_sql}')"
    ).fetchone()[0]
    connection.close()
    return AggregationResult(output_path, minutes, int(rows_written))
