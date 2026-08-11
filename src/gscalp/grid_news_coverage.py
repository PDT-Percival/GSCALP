from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .grid_config import GridConfig
from .grid_news import NewsCode, news_gate
from .news_sessions import candidate_sessions, grid_session_spec


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


def build_news_coverage_report(
    config: GridConfig,
    market_root: Path | str,
    news_path: Path | str,
    *,
    buffer: pd.Timedelta = pd.Timedelta(0),
) -> NewsCoverageReport:
    items: list[NewsCoverageItem] = []
    counts: Counter[str] = Counter()
    for session in candidate_sessions(market_root, grid_session_spec(config)):
        decision = news_gate(
            news_path,
            session.start_utc,
            session.end_utc,
            buffer,
        )
        row = decision.matching_rows[0] if decision.matching_rows else {}
        item = NewsCoverageItem(
            local_date=session.local_date,
            window=session.window,
            session_start_utc=session.start_utc.isoformat(),
            session_end_utc=session.end_utc.isoformat(),
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
