from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .config import StrategyConfig


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class LevelSide(str, Enum):
    LOW = "low"
    HIGH = "high"


class ReasonCode(str, Enum):
    NEUTRAL_M15 = "neutral_m15"
    NO_LEVEL_SWEEP = "no_level_sweep"
    SWEEP_TOO_SMALL = "sweep_too_small"
    SWEEP_TOO_DEEP = "sweep_too_deep"
    SWEEP_DETECTED = "sweep_detected"
    NO_RECLAIM = "no_reclaim"
    RECLAIMED = "reclaimed"
    WEAK_DISPLACEMENT = "weak_displacement"
    DISPLACED = "displaced"
    NO_RETEST = "no_retest"
    RETESTED = "retested"
    STOP_TOO_WIDE = "stop_too_wide"
    INSUFFICIENT_ROOM = "insufficient_room"
    QUALIFIED = "qualified"


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    name: str
    price: float
    side: LevelSide


@dataclass(frozen=True, slots=True)
class StrategyContext:
    as_of: pd.Timestamp
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    m15: pd.DataFrame
    m5: pd.DataFrame
    levels: tuple[LiquidityLevel, ...]
    spread: float
    config: "StrategyConfig"

    def __post_init__(self) -> None:
        timestamps = (self.as_of, self.session_start, self.session_end)
        if any(item.tzinfo is None for item in timestamps):
            raise ValueError("strategy context timestamps must be timezone-aware")
        if self.session_end - self.session_start != pd.Timedelta(minutes=60):
            raise ValueError("strategy session must be exactly 60 minutes")


@dataclass(frozen=True, slots=True)
class SignalDecision:
    eligible: bool
    direction: Direction | None
    signal_time: pd.Timestamp | None
    entry: float | None
    stop: float | None
    target: float | None
    reasons: tuple[ReasonCode, ...]
    level_name: str | None = None
    diagnostics: tuple[tuple[str, Any], ...] = ()
