from __future__ import annotations

import json
import math
from dataclasses import MISSING, dataclass, fields
from datetime import date, datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Any


_VERSION = "pullback-v1.1"
_TERMINAL_PATH = r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
_SERVER = "FBS-Demo"
_SYMBOL = "XAUUSD"
_SESSIONS = ("08:45-09:45", "09:30-10:30", "10:00-11:00")
_TIMEFRAMES = ("M1", "M5")
_TARGETS = (0.35, 0.50, 0.65)
_PARTITION_DATES = (date(2023, 11, 29), date(2025, 3, 24), date(2026, 7, 15))


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
class PullbackCandidate:
    session_ny: str
    trigger_timeframe: str
    target_r: float
    abort_timeframe: str

    def __post_init__(self) -> None:
        if self.session_ny not in _SESSIONS:
            raise ValueError("candidate session is outside the frozen search space")
        if self.trigger_timeframe not in _TIMEFRAMES:
            raise ValueError("candidate trigger timeframe must be M1 or M5")
        if float(self.target_r) not in _TARGETS:
            raise ValueError("candidate target is outside the frozen search space")
        if self.abort_timeframe not in _TIMEFRAMES:
            raise ValueError("candidate abort timeframe must be M1 or M5")

    @property
    def candidate_id(self) -> str:
        session = self.session_ny.replace(":", "").replace("-", "_")
        return (
            f"{session}__{self.trigger_timeframe}__{self.target_r:.2f}R"
            f"__abort_{self.abort_timeframe}"
        )


@dataclass(frozen=True, slots=True)
class PullbackConfig:
    version: str
    terminal_path: str
    required_server: str
    symbol: str
    mode: str
    required_margin_mode: int
    candidate_sessions_ny: tuple[str, ...]
    trigger_timeframes: tuple[str, ...]
    target_r_candidates: tuple[float, ...]
    abort_timeframes: tuple[str, ...]
    bias_ema_period: int
    bias_slope_bars: int
    trigger_ema_period: int
    atr_period: int
    trigger_body_fraction_min: float
    pullback_atr_min: float
    pullback_atr_max: float
    stop_buffer_atr: float
    stop_buffer_spread_multiple: float
    stop_atr_min: float
    stop_atr_max: float
    reference_spread_minutes: int
    current_spread_multiple: float
    nominal_risk_fraction: float
    absolute_risk_fraction: float
    risk_reserve_fraction: float
    max_margin_fraction: float
    entry_cutoff_minute: int
    session_minutes: int
    max_trade_attempts_per_session: int
    development_end: date
    validation_end: date
    test_end: date

    def __post_init__(self) -> None:
        for name in (
            "candidate_sessions_ny",
            "trigger_timeframes",
            "target_r_candidates",
            "abort_timeframes",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if self.version != _VERSION:
            raise ValueError(f"version must be exactly {_VERSION}")
        if self.terminal_path != _TERMINAL_PATH:
            raise ValueError(f"terminal_path must be exactly {_TERMINAL_PATH}")
        if self.required_server != _SERVER:
            raise ValueError(f"required_server must be exactly {_SERVER}")
        if self.symbol != _SYMBOL:
            raise ValueError(f"symbol must be exactly {_SYMBOL}")
        if self.mode != "shadow":
            raise ValueError("mode must be exactly shadow")
        if self.required_margin_mode != 2:
            raise ValueError("required_margin_mode must be MT5 retail hedging (2)")
        if self.candidate_sessions_ny != _SESSIONS:
            raise ValueError("candidate sessions must match the frozen v1.1 set")
        if any(_session_minutes(item) != 60 for item in self.candidate_sessions_ny):
            raise ValueError("candidate sessions must each be exactly 60 minutes")
        if self.trigger_timeframes != _TIMEFRAMES:
            raise ValueError("trigger timeframes must be exactly M1 and M5")
        if self.target_r_candidates != _TARGETS:
            raise ValueError("target candidates must be exactly 0.35R, 0.50R, 0.65R")
        if self.abort_timeframes != _TIMEFRAMES:
            raise ValueError("abort timeframes must be exactly M1 and M5")
        if self.bias_ema_period != 20 or self.bias_slope_bars != 3:
            raise ValueError("bias must use EMA(20) with a three-bar slope")
        if self.trigger_ema_period != 9 or self.atr_period != 14:
            raise ValueError("trigger EMA and ATR periods must be 9 and 14")
        if self.trigger_body_fraction_min != 0.35:
            raise ValueError("trigger body fraction must be exactly 0.35")
        if (self.pullback_atr_min, self.pullback_atr_max) != (0.25, 1.10):
            raise ValueError("pullback ATR bounds must be exactly 0.25 and 1.10")
        if (self.stop_buffer_atr, self.stop_buffer_spread_multiple) != (0.10, 2.0):
            raise ValueError("stop buffer values must match the frozen design")
        if (self.stop_atr_min, self.stop_atr_max) != (0.35, 1.50):
            raise ValueError("stop ATR bounds must be exactly 0.35 and 1.50")
        if self.reference_spread_minutes != 30 or self.current_spread_multiple != 2.0:
            raise ValueError("spread controls must match the frozen design")
        if not 0 < self.nominal_risk_fraction <= 0.0020:
            raise ValueError("nominal risk must not exceed 0.20%")
        if not 0 < self.absolute_risk_fraction <= 0.0025:
            raise ValueError("absolute risk must not exceed 0.25%")
        if not math.isclose(
            self.risk_reserve_fraction,
            self.absolute_risk_fraction - self.nominal_risk_fraction,
            abs_tol=1e-12,
        ):
            raise ValueError("risk reserve must equal absolute risk minus nominal risk")
        if not 0 < self.max_margin_fraction <= 0.10:
            raise ValueError("maximum margin fraction must not exceed 10%")
        if self.entry_cutoff_minute != 45:
            raise ValueError("entry cutoff must be minute 45")
        if self.session_minutes != 60:
            raise ValueError("session must be exactly 60 minutes")
        if self.max_trade_attempts_per_session != 1:
            raise ValueError("only one trade attempt is permitted")
        if (self.development_end, self.validation_end, self.test_end) != _PARTITION_DATES:
            raise ValueError("partition dates must match the frozen v1.1 boundaries")

    def candidates(self) -> tuple[PullbackCandidate, ...]:
        return tuple(
            PullbackCandidate(session, trigger, target, abort)
            for session, trigger, target, abort in product(
                self.candidate_sessions_ny,
                self.trigger_timeframes,
                self.target_r_candidates,
                self.abort_timeframes,
            )
        )


def load_pullback_config(path: Path | str) -> PullbackConfig:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    known = {item.name for item in fields(PullbackConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown configuration keys: {', '.join(unknown)}")
    missing = sorted(
        item.name
        for item in fields(PullbackConfig)
        if item.default is MISSING
        and item.default_factory is MISSING
        and item.name not in raw
    )
    if missing:
        raise ValueError(f"missing configuration keys: {', '.join(missing)}")
    for name in (
        "candidate_sessions_ny",
        "trigger_timeframes",
        "target_r_candidates",
        "abort_timeframes",
    ):
        raw[name] = tuple(raw[name])
    for name in ("development_end", "validation_end", "test_end"):
        raw[name] = date.fromisoformat(raw[name])
    return PullbackConfig(**raw)
