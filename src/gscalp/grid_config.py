from __future__ import annotations

import json
from dataclasses import MISSING, dataclass, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


_ALLOWED_MODES = frozenset({"read_only", "shadow", "demo"})
_VERSION = "grid-v1.0"
_TERMINAL_PATH = r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
_SERVER = "FBS-Demo"
_SYMBOL = "XAUUSD"
_LEVEL_FRACTIONS = (0.25, 0.50, 0.75)


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
class GridConfig:
    version: str
    terminal_path: str
    required_server: str
    symbol: str
    mode: str
    required_margin_mode: int
    candidate_sessions_ny: tuple[str, ...]
    ema_period: int
    atr_period: int
    pivot_left: int
    pivot_right: int
    pivot_lookback: int
    stop_buffer_atr: float
    stop_buffer_spread_multiple: float
    invalidation_atr_min: float
    invalidation_atr_max: float
    level_fractions: tuple[float, float, float]
    profit_distance_fraction: float
    reference_spread_multiple: float
    current_spread_multiple: float
    profit_distance_max_fraction: float
    nominal_risk_fraction: float
    absolute_risk_fraction: float
    max_margin_fraction: float
    pending_expiry_minute: int
    session_minutes: int
    max_baskets_per_session: int
    development_end: date
    validation_end: date
    test_end: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_sessions_ny", tuple(self.candidate_sessions_ny))
        object.__setattr__(self, "level_fractions", tuple(self.level_fractions))
        if self.version != _VERSION:
            raise ValueError(f"version must be exactly {_VERSION}")
        if self.terminal_path != _TERMINAL_PATH:
            raise ValueError(f"terminal_path must be exactly {_TERMINAL_PATH}")
        if self.required_server != _SERVER:
            raise ValueError(f"required_server must be exactly {_SERVER}")
        if self.symbol != _SYMBOL:
            raise ValueError(f"symbol must be exactly {_SYMBOL}")
        if self.mode not in _ALLOWED_MODES:
            raise ValueError("mode must be one of: demo, read_only, shadow")
        if self.required_margin_mode != 2:
            raise ValueError("required_margin_mode must be MT5 retail hedging (2)")
        if len(self.candidate_sessions_ny) != 2:
            raise ValueError("candidate_sessions_ny must contain exactly two sessions")
        if any(_session_minutes(window) != 60 for window in self.candidate_sessions_ny):
            raise ValueError("every candidate session must be exactly 60 minutes")
        if self.level_fractions != _LEVEL_FRACTIONS:
            raise ValueError("level_fractions must be exactly (0.25, 0.50, 0.75)")
        if not 0 < self.nominal_risk_fraction <= 0.0020:
            raise ValueError("nominal_risk_fraction must not exceed 0.0020")
        if not 0 < self.absolute_risk_fraction <= 0.0025:
            raise ValueError("absolute_risk_fraction must not exceed 0.0025")
        if self.absolute_risk_fraction < self.nominal_risk_fraction:
            raise ValueError("absolute_risk_fraction must be at least nominal_risk_fraction")
        if not 0 < self.max_margin_fraction <= 0.10:
            raise ValueError("max_margin_fraction must be between 0 and 0.10")
        if self.pending_expiry_minute != 45:
            raise ValueError("pending_expiry_minute must be exactly 45")
        if self.session_minutes != 60:
            raise ValueError("session_minutes must be exactly 60")
        if self.max_baskets_per_session != 1:
            raise ValueError("max_baskets_per_session must be exactly one")
        if self.development_end >= self.validation_end or self.validation_end >= self.test_end:
            raise ValueError("partition dates must be strictly ordered")
        if self.ema_period < 2 or self.atr_period < 2:
            raise ValueError("indicator periods must be at least two")
        if self.pivot_left < 1 or self.pivot_right < 1 or self.pivot_lookback < 1:
            raise ValueError("pivot settings must be positive")
        if not 0 < self.stop_buffer_atr:
            raise ValueError("stop_buffer_atr must be positive")
        if not 0 < self.stop_buffer_spread_multiple:
            raise ValueError("stop_buffer_spread_multiple must be positive")
        if not 0 < self.invalidation_atr_min < self.invalidation_atr_max:
            raise ValueError("invalidation ATR bounds are invalid")
        if not 0 < self.profit_distance_fraction <= self.profit_distance_max_fraction:
            raise ValueError("profit distance fractions are invalid")
        if self.reference_spread_multiple <= 0 or self.current_spread_multiple <= 0:
            raise ValueError("spread multiples must be positive")


def load_grid_config(path: Path | str) -> GridConfig:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {item.name for item in fields(GridConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown configuration keys: {', '.join(unknown)}")
    missing = sorted(
        item.name
        for item in fields(GridConfig)
        if item.default is MISSING and item.default_factory is MISSING and item.name not in raw
    )
    if missing:
        raise ValueError(f"missing configuration keys: {', '.join(missing)}")
    raw["candidate_sessions_ny"] = tuple(raw["candidate_sessions_ny"])
    raw["level_fractions"] = tuple(raw["level_fractions"])
    for field_name in ("development_end", "validation_end", "test_end"):
        raw[field_name] = date.fromisoformat(raw[field_name])
    return GridConfig(**raw)
