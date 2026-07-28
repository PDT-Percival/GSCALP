from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from .grid_config import GridConfig
from .grid_news import NewsCode, news_gate
from .research import new_york_session_bounds


_DEVELOPMENT_START = date(2020, 1, 2)


@dataclass(frozen=True, slots=True)
class NewsCoverageItem:
    local_date: date
    window: str
    session_start_utc: str
    session_end_utc: str
    code: str
    event_name: str
    source: str

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["local_date"] = self.local_date.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class NewsCoverageReport:
    total_sessions: int
    counts: dict[str, int]
    ready: bool
    items: tuple[NewsCoverageItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "total_sessions": self.total_sessions,
            "counts": self.counts,
            "ready": self.ready,
            "items": [item.to_json_dict() for item in self.items],
        }


def _m5_candidate_dates(market_root: Path, config: GridConfig) -> tuple[date, ...]:
    path = (market_root / "bars" / "M5.parquet").as_posix().replace("'", "''")
    frame = duckdb.sql(
        f"""
        SELECT DISTINCT CAST(Timestamp AS DATE) AS utc_date
        FROM read_parquet('{path}')
        ORDER BY utc_date
        """
    ).df()
    if frame.empty:
        return ()
    ny = ZoneInfo("America/New_York")
    dates: set[date] = set()
    for value in pd.to_datetime(frame["utc_date"]):
        utc_start = pd.Timestamp(value).tz_localize("UTC")
        for offset in range(-1, 2):
            local_date = (utc_start + pd.Timedelta(days=offset)).tz_convert(ny).date()
            if _DEVELOPMENT_START <= local_date <= config.test_end:
                dates.add(local_date)
    return tuple(sorted(dates))


def build_news_coverage_report(
    config: GridConfig,
    market_root: Path | str,
    news_path: Path | str,
    *,
    buffer: pd.Timedelta = pd.Timedelta(0),
) -> NewsCoverageReport:
    items: list[NewsCoverageItem] = []
    counts: Counter[str] = Counter()
    for local_date in _m5_candidate_dates(Path(market_root), config):
        for window in config.candidate_sessions_ny:
            session_start, session_end = new_york_session_bounds(local_date, window)
            decision = news_gate(news_path, session_start, session_end, buffer)
            row = decision.matching_rows[0] if decision.matching_rows else {}
            item = NewsCoverageItem(
                local_date=local_date,
                window=window,
                session_start_utc=session_start.isoformat(),
                session_end_utc=session_end.isoformat(),
                code=decision.code.value,
                event_name=row.get("event_name", ""),
                source=row.get("source", ""),
            )
            items.append(item)
            counts[decision.code.value] += 1
    ready = bool(items) and set(counts) == {NewsCode.CLEAR.value}
    return NewsCoverageReport(
        total_sessions=len(items),
        counts=dict(counts),
        ready=ready,
        items=tuple(items),
    )
