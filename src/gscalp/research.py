from __future__ import annotations

from datetime import date, datetime, time
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from .config import StrategyConfig
from .models import LevelSide, LiquidityLevel, SignalDecision, StrategyContext
from .strategy import evaluate_setup


NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class SessionEvaluation:
    local_date: date
    window: str
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    decisions: tuple[SignalDecision, ...]
    qualified_signals: tuple[SignalDecision, ...]


def new_york_session_bounds(
    local_date: date, window: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        start_text, end_text = window.split("-", maxsplit=1)
        start_time = time.fromisoformat(start_text)
        end_time = time.fromisoformat(end_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid New York session window: {window!r}") from exc
    start_local = datetime.combine(local_date, start_time, tzinfo=NEW_YORK)
    end_local = datetime.combine(local_date, end_time, tzinfo=NEW_YORK)
    if end_local <= start_local:
        end_local = end_local.replace(day=end_local.day + 1)
    return (
        pd.Timestamp(start_local.astimezone(UTC)),
        pd.Timestamp(end_local.astimezone(UTC)),
    )


def _level_pair(name: str, bars: pd.DataFrame) -> tuple[LiquidityLevel, LiquidityLevel]:
    if bars.empty:
        raise ValueError(f"no completed bars for {name} liquidity levels")
    return (
        LiquidityLevel(f"{name}_high", float(bars["high"].max()), LevelSide.HIGH),
        LiquidityLevel(f"{name}_low", float(bars["low"].min()), LevelSide.LOW),
    )


def build_liquidity_levels(
    bars: pd.DataFrame, session_start: pd.Timestamp
) -> tuple[LiquidityLevel, ...]:
    if bars.index.tz is None or session_start.tzinfo is None:
        raise ValueError("bars and session_start must be timezone-aware")
    utc = bars.copy()
    utc.index = utc.index.tz_convert("UTC")
    session_start = session_start.tz_convert("UTC")
    completed = utc.loc[utc.index < session_start]
    current_date = session_start.date()
    previous_dates = sorted({item for item in completed.index.date if item < current_date})
    if not previous_dates:
        raise ValueError("no previous trading day is available")
    previous_date = previous_dates[-1]
    previous_day = completed.loc[completed.index.date == previous_date]
    current = completed.loc[completed.index.date == current_date]
    local_times = current.index.time
    asian = current.loc[[item < time(8, 0) for item in local_times]]
    london = current.loc[
        [time(8, 0) <= item < time(12, 0) for item in local_times]
    ]
    return (
        *_level_pair("previous_day", previous_day),
        *_level_pair("asian", asian),
        *_level_pair("london", london),
    )


def build_liquidity_level_map(
    bars: pd.DataFrame,
) -> dict[date, tuple[LiquidityLevel, ...]]:
    """Build each UTC trading day's completed reference levels in one pass."""
    if bars.index.tz is None:
        raise ValueError("bars must be timezone-aware")
    utc = bars if str(bars.index.tz) == "UTC" else bars.tz_convert("UTC")
    day_keys = pd.Series(utc.index.date, index=utc.index)
    daily = utc.groupby(day_keys, sort=True).agg({"high": "max", "low": "min"})
    trading_dates = list(daily.index)
    result: dict[date, tuple[LiquidityLevel, ...]] = {}
    for position in range(1, len(trading_dates)):
        current_date = trading_dates[position]
        previous_date = trading_dates[position - 1]
        day = utc.loc[str(current_date)]
        local_times = day.index.time
        asian = day.loc[[item < time(8, 0) for item in local_times]]
        london = day.loc[
            [time(8, 0) <= item < time(12, 0) for item in local_times]
        ]
        if asian.empty or london.empty:
            continue
        previous = daily.loc[[previous_date]]
        result[current_date] = (
            *_level_pair("previous_day", previous),
            *_level_pair("asian", asian),
            *_level_pair("london", london),
        )
    return result


def load_bar_parquet(path: Path | str) -> pd.DataFrame:
    source = Path(path).resolve().as_posix().replace("'", "''")
    frame = duckdb.sql(
        f"SELECT * FROM read_parquet('{source}') ORDER BY Timestamp"
    ).df()
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True)
    frame = frame.set_index("Timestamp")
    return frame.rename(
        columns={
            "BidOpen": "open",
            "BidHigh": "high",
            "BidLow": "low",
            "BidClose": "close",
            "AskOpen": "ask_open",
            "AskHigh": "ask_high",
            "AskLow": "ask_low",
            "AskClose": "ask_close",
            "TickCount": "tick_count",
            "MinSpread": "min_spread",
            "MaxSpread": "max_spread",
        }
    )


class TickParquetStore:
    def __init__(self, path_pattern: Path | str) -> None:
        self.path_pattern = Path(path_pattern).resolve().as_posix()

    def slice(self, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> pd.DataFrame:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("tick slice bounds must be timezone-aware")
        pattern = self.path_pattern.replace("'", "''")
        start = start_utc.tz_convert("UTC").tz_localize(None)
        end = end_utc.tz_convert("UTC").tz_localize(None)
        frame = duckdb.sql(
            f"""
            SELECT Timestamp, Bid, Ask
            FROM read_parquet('{pattern}', hive_partitioning=true)
            WHERE Timestamp >= TIMESTAMP '{start}'
              AND Timestamp < TIMESTAMP '{end}'
            ORDER BY Timestamp
            """
        ).df()
        if frame.empty:
            return pd.DataFrame(
                columns=["bid", "ask"],
                index=pd.DatetimeIndex([], name="time", tz="UTC"),
            )
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True)
        return frame.set_index("Timestamp")[["Bid", "Ask"]].rename(
            columns={"Bid": "bid", "Ask": "ask"}
        )


def evaluate_session_bounds(
    m5: pd.DataFrame,
    m15: pd.DataFrame,
    levels: tuple[LiquidityLevel, ...],
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
    config: StrategyConfig,
    *,
    window: str,
) -> SessionEvaluation:
    session_left = int(m5.index.searchsorted(session_start, side="left"))
    session_right = int(m5.index.searchsorted(session_end, side="left"))
    decisions: list[SignalDecision] = []
    qualified: list[SignalDecision] = []
    seen: set[tuple[object, ...]] = set()
    warmup_rows = max(config.atr_period + 10, 30)
    regime_rows = config.ema_period + 10
    for m5_position in range(session_left, session_right):
        timestamp = m5.index[m5_position]
        bar = m5.iloc[m5_position]
        as_of = timestamp + pd.Timedelta(minutes=5)
        if as_of > session_end:
            continue
        m5_window = m5.iloc[max(0, m5_position + 1 - warmup_rows) : m5_position + 1]
        m15_right = int(m15.index.searchsorted(as_of, side="left"))
        m15_window = m15.iloc[max(0, m15_right - regime_rows) : m15_right]
        if "max_spread" in bar:
            spread = float(bar["max_spread"])
        elif "ask_close" in bar:
            spread = float(bar["ask_close"] - bar["close"])
        else:
            spread = 0.0
        decision = evaluate_setup(
            StrategyContext(
                as_of=as_of,
                session_start=session_start,
                session_end=session_end,
                m15=m15_window,
                m5=m5_window,
                levels=levels,
                spread=spread,
                config=config,
            )
        )
        decisions.append(decision)
        if decision.eligible:
            key = (decision.direction, decision.signal_time, decision.level_name)
            if key not in seen:
                seen.add(key)
                qualified.append(decision)
    local_date = session_start.tz_convert(NEW_YORK).date()
    return SessionEvaluation(
        local_date=local_date,
        window=window,
        session_start=session_start,
        session_end=session_end,
        decisions=tuple(decisions),
        qualified_signals=tuple(qualified),
    )
