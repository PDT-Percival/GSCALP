from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


def _require_timezone_aware(*timestamps: pd.Timestamp) -> None:
    if any(getattr(timestamp, "tzinfo", None) is None for timestamp in timestamps):
        raise ValueError("timestamps must be timezone-aware")


def _require_three_ordered(values: tuple[float, ...], name: str) -> None:
    if len(values) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    increasing = all(left < right for left, right in zip(values, values[1:]))
    decreasing = all(left > right for left, right in zip(values, values[1:]))
    if not (increasing or decreasing):
        raise ValueError(f"{name} must be strictly monotonic")


class BiasDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class GridReason(str, Enum):
    BIAS_LOCKED = "bias_locked"
    NEUTRAL_BIAS = "neutral_bias"
    ATR_UNAVAILABLE = "atr_unavailable"
    NO_CONFIRMED_PIVOT = "no_confirmed_pivot"
    INVALIDATION_TOO_CLOSE = "invalidation_too_close"
    INVALIDATION_TOO_FAR = "invalidation_too_far"
    SPREAD_TOO_WIDE = "spread_too_wide"
    NEWS_BLOCKED = "news_blocked"
    BROKER_DISTANCE_INVALID = "broker_distance_invalid"
    VOLUME_BELOW_MINIMUM = "volume_below_minimum"
    BASKET_RISK_EXCEEDED = "basket_risk_exceeded"
    MARGIN_LIMIT_EXCEEDED = "margin_limit_exceeded"
    EXISTING_EXPOSURE = "existing_exposure"
    GRID_ARMED = "grid_armed"
    LEVEL_1_FILLED = "level_1_filled"
    LEVEL_2_FILLED = "level_2_filled"
    LEVEL_3_FILLED = "level_3_filled"
    BIAS_ABORT = "bias_abort"
    TARGET_CLOSED = "target_closed"
    STOPPED = "stopped"
    PENDING_EXPIRED = "pending_expired"
    SESSION_FLATTENED = "session_flattened"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class BiasDecision:
    direction: BiasDirection | None
    reason: GridReason
    as_of: pd.Timestamp
    ema_now: float | None
    ema_three_bars_ago: float | None

    def __post_init__(self) -> None:
        _require_timezone_aware(self.as_of)


@dataclass(frozen=True, slots=True)
class GridGeometry:
    direction: BiasDirection
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    anchor: float
    stop: float
    atr: float
    reference_spread: float
    current_spread: float
    profit_distance: float
    level_prices: tuple[float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "level_prices", tuple(self.level_prices))
        _require_timezone_aware(self.session_start, self.session_end)
        if self.session_end <= self.session_start:
            raise ValueError("session_end must be after session_start")
        _require_three_ordered(self.level_prices, "level_prices")


@dataclass(frozen=True, slots=True)
class GridLevelPlan:
    level_number: int
    requested_price: float
    volume: float
    stop: float
    provisional_target: float

    def __post_init__(self) -> None:
        if self.level_number not in (1, 2, 3):
            raise ValueError("level_number must be 1, 2, or 3")
        if self.volume <= 0:
            raise ValueError("volume must be positive")


@dataclass(frozen=True, slots=True)
class GridPlan:
    basket_id: str
    geometry: GridGeometry
    levels: tuple[GridLevelPlan, GridLevelPlan, GridLevelPlan]
    projected_loss_cash: float
    projected_margin_cash: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "levels", tuple(self.levels))
        if len(self.levels) != 3:
            raise ValueError("levels must contain exactly three plans")
        if tuple(level.level_number for level in self.levels) != (1, 2, 3):
            raise ValueError("levels must be ordered 1, 2, 3")
        _require_three_ordered(tuple(level.requested_price for level in self.levels), "levels")
        if len({level.volume for level in self.levels}) != 1:
            raise ValueError("grid levels must have equal volume")


@dataclass(frozen=True, slots=True)
class LegResult:
    level_number: int
    fill_time: pd.Timestamp
    fill_price: float
    exit_time: pd.Timestamp
    exit_price: float
    volume: float
    reason: GridReason
    pnl_cash: float

    def __post_init__(self) -> None:
        _require_timezone_aware(self.fill_time, self.exit_time)
        if self.exit_time < self.fill_time:
            raise ValueError("exit_time cannot precede fill_time")


@dataclass(frozen=True, slots=True)
class BasketResult:
    basket_id: str
    direction: BiasDirection
    session_start: pd.Timestamp
    exit_time: pd.Timestamp
    reason: GridReason
    legs: tuple[LegResult, ...]
    gross_r: float
    cost_r: float
    net_r: float
    mfe_r: float
    mae_r: float
    maximum_levels_filled: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "legs", tuple(self.legs))
        _require_timezone_aware(self.session_start, self.exit_time)
        if self.exit_time < self.session_start:
            raise ValueError("exit_time cannot precede session_start")
        if not 0 <= self.maximum_levels_filled <= 3:
            raise ValueError("maximum_levels_filled must be between 0 and 3")
