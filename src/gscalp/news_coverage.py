from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .grid_news import NewsCode, news_gate
from .news_sessions import StrategySessionSpec, candidate_sessions


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
    strategy_version: str
    total_sessions: int
    counts: dict[str, int]
    coverage_complete: bool
    all_sessions_clear: bool
    ready: bool
    items: tuple[NewsCoverageItem, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy_version": self.strategy_version,
            "total_sessions": self.total_sessions,
            "counts": self.counts,
            "coverage_complete": self.coverage_complete,
            "all_sessions_clear": self.all_sessions_clear,
            "ready": self.ready,
            "items": [item.to_json_dict() for item in self.items],
        }


def build_strategy_news_coverage_report(
    spec: StrategySessionSpec,
    market_root: Path | str,
    news_path: Path | str,
    *,
    buffer: pd.Timedelta = pd.Timedelta(0),
) -> NewsCoverageReport:
    items: list[NewsCoverageItem] = []
    counts: Counter[str] = Counter()
    for session in candidate_sessions(market_root, spec):
        decision = news_gate(
            news_path,
            session.start_utc,
            session.end_utc,
            buffer,
        )
        row = decision.matching_rows[0] if decision.matching_rows else {}
        items.append(
            NewsCoverageItem(
                local_date=session.local_date,
                window=session.window,
                session_start_utc=session.start_utc.isoformat(),
                session_end_utc=session.end_utc.isoformat(),
                code=decision.code.value,
                event_name=row.get("event_name", ""),
                source=row.get("source", ""),
            )
        )
        counts[decision.code.value] += 1

    complete_codes = {
        NewsCode.CLEAR.value,
        NewsCode.OVERLAPPING_BLACKOUT.value,
    }
    coverage_complete = bool(items) and all(
        item.code in complete_codes for item in items
    )
    all_sessions_clear = coverage_complete and all(
        item.code == NewsCode.CLEAR.value for item in items
    )
    return NewsCoverageReport(
        strategy_version=spec.version,
        total_sessions=len(items),
        counts=dict(counts),
        coverage_complete=coverage_complete,
        all_sessions_clear=all_sessions_clear,
        ready=coverage_complete,
        items=tuple(items),
    )
