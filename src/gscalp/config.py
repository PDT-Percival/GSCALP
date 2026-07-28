from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ALLOWED_MODES = frozenset({"read_only", "shadow", "demo"})


def _session_minutes(value: str) -> int:
    try:
        start_text, end_text = value.split("-", maxsplit=1)
        start = datetime.strptime(start_text, "%H:%M")
        end = datetime.strptime(end_text, "%H:%M")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid session window: {value!r}") from exc
    if end <= start:
        end += timedelta(days=1)
    return int((end - start).total_seconds() // 60)


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    terminal_path: str
    required_server: str
    symbol: str
    mode: str
    risk_per_trade: float
    daily_loss_limit: float
    max_trades: int
    candidate_sessions_ny: tuple[str, ...]
    ema_period: int
    atr_period: int
    sweep_atr_min: float
    sweep_atr_max: float
    displacement_atr_min: float
    max_stop_atr: float
    minimum_room_r: float
    target_r: float
    allow_same_bar_reclaim: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_sessions_ny", tuple(self.candidate_sessions_ny)
        )
        if self.mode not in ALLOWED_MODES:
            allowed = ", ".join(sorted(ALLOWED_MODES))
            raise ValueError(f"mode must be one of: {allowed}")
        if self.required_server != "FBS-Demo":
            raise ValueError("required_server must be exactly FBS-Demo")
        if not 0 < self.risk_per_trade <= 0.0025:
            raise ValueError("risk_per_trade must be between 0 and 0.0025")
        if not 0 < self.daily_loss_limit <= 0.005:
            raise ValueError("daily_loss_limit must be between 0 and 0.005")
        if not 1 <= self.max_trades <= 2:
            raise ValueError("max_trades must be one or two")
        if not self.candidate_sessions_ny:
            raise ValueError("candidate_sessions_ny cannot be empty")
        if any(_session_minutes(window) != 60 for window in self.candidate_sessions_ny):
            raise ValueError("every candidate session must be exactly 60 minutes")
        if self.ema_period < 2 or self.atr_period < 2:
            raise ValueError("indicator periods must be at least two")
        if not 0 < self.sweep_atr_min < self.sweep_atr_max:
            raise ValueError("sweep ATR bounds are invalid")
        if self.displacement_atr_min <= 0 or self.max_stop_atr <= 0:
            raise ValueError("ATR thresholds must be positive")
        if self.minimum_room_r <= 0 or self.target_r <= 0:
            raise ValueError("R thresholds must be positive")
        if not isinstance(self.allow_same_bar_reclaim, bool):
            raise ValueError("allow_same_bar_reclaim must be boolean")


def load_config(path: Path | str) -> StrategyConfig:
    config_path = Path(path)
    payload: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    known = {item.name for item in fields(StrategyConfig)}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValueError(f"unknown configuration keys: {', '.join(unknown)}")
    required = {
        item.name
        for item in fields(StrategyConfig)
        if item.default is MISSING and item.default_factory is MISSING
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"missing configuration keys: {', '.join(missing)}")
    return StrategyConfig(**payload)
