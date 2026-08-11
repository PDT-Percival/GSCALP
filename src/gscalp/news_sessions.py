from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from .grid_config import GridConfig
from .pullback_config import PullbackConfig
from .research import new_york_session_bounds


FIRST_RESEARCH_DATE = date(2020, 1, 2)
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class StrategySessionSpec:
    version: str
    windows_ny: tuple[str, ...]
    first_date: date
    last_date: date


@dataclass(frozen=True, slots=True)
class CandidateSession:
    version: str
    local_date: date
    window: str
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp


def grid_session_spec(config: GridConfig) -> StrategySessionSpec:
    return StrategySessionSpec(
        version=config.version,
        windows_ny=config.candidate_sessions_ny,
        first_date=FIRST_RESEARCH_DATE,
        last_date=config.test_end,
    )


def pullback_session_spec(config: PullbackConfig) -> StrategySessionSpec:
    return StrategySessionSpec(
        version=config.version,
        windows_ny=config.candidate_sessions_ny,
        first_date=FIRST_RESEARCH_DATE,
        last_date=config.test_end,
    )


def _m5_local_dates(market_root: Path) -> tuple[date, ...]:
    path = (market_root / "bars" / "M5.parquet").as_posix().replace("'", "''")
    frame = duckdb.sql(
        f"""
        SELECT Timestamp
        FROM read_parquet('{path}')
        ORDER BY Timestamp
        """
    ).df()
    if frame.empty:
        return ()
    timestamps = pd.to_datetime(frame["Timestamp"], utc=True)
    return tuple(sorted(set(timestamps.dt.tz_convert(NEW_YORK).dt.date)))


def candidate_sessions(
    market_root: Path | str,
    spec: StrategySessionSpec,
) -> tuple[CandidateSession, ...]:
    sessions: list[CandidateSession] = []
    for local_date in _m5_local_dates(Path(market_root)):
        if not spec.first_date <= local_date <= spec.last_date:
            continue
        for window in spec.windows_ny:
            start, end = new_york_session_bounds(local_date, window)
            sessions.append(
                CandidateSession(
                    version=spec.version,
                    local_date=local_date,
                    window=window,
                    start_utc=start,
                    end_utc=end,
                )
            )
    return tuple(
        sorted(sessions, key=lambda item: (item.local_date, item.window))
    )
