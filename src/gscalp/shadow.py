from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .models import SignalDecision


@dataclass(frozen=True, slots=True)
class ShadowRecord:
    terminal_path: str
    server: str
    symbol: str
    bar_time: pd.Timestamp
    new_york_time: pd.Timestamp
    bar: Mapping[str, float]
    indicators: Mapping[str, float]
    levels: Mapping[str, float]
    state: str
    spread: float
    decision: SignalDecision

    def __post_init__(self) -> None:
        if self.bar_time.tzinfo is None or self.new_york_time.tzinfo is None:
            raise ValueError("shadow timestamps must be timezone-aware")


class ShadowLogger:
    """Append-only decision journal with deliberately no trading interface."""

    def __init__(self, path: Path | str, read_source: Any) -> None:
        self.path = Path(path)
        self._read_source = read_source
        self._seen = self._load_seen()

    def _load_seen(self) -> set[tuple[str, str, str]]:
        if not self.path.exists():
            return set()
        seen: set[tuple[str, str, str]] = set()
        for number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                seen.add((item["server"], item["symbol"], item["bar_time"]))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"invalid shadow journal line {number}") from exc
        return seen

    def append(self, record: ShadowRecord, *, observed_at: pd.Timestamp) -> bool:
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        completed_at = record.bar_time + pd.Timedelta(minutes=5)
        if observed_at < completed_at:
            raise ValueError("only a completed M5 bar may be logged")
        bar_time = record.bar_time.isoformat()
        key = (record.server, record.symbol, bar_time)
        if key in self._seen:
            return False
        decision = record.decision
        payload = {
            "terminal_path": record.terminal_path,
            "server": record.server,
            "symbol": record.symbol,
            "observed_at": observed_at.isoformat(),
            "bar_time": bar_time,
            "new_york_time": record.new_york_time.isoformat(),
            "bar": dict(record.bar),
            "indicators": dict(record.indicators),
            "levels": dict(record.levels),
            "state": record.state,
            "spread": record.spread,
            "eligible": decision.eligible,
            "direction": None if decision.direction is None else decision.direction.value,
            "signal_time": None
            if decision.signal_time is None
            else decision.signal_time.isoformat(),
            "entry": decision.entry,
            "stop": decision.stop,
            "target": decision.target,
            "level_name": decision.level_name,
            "reasons": [item.value for item in decision.reasons],
            "diagnostics": dict(decision.diagnostics),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
        self._seen.add(key)
        return True
