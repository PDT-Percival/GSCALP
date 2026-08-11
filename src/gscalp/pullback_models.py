from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd

from .pullback_config import PullbackCandidate


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TriggerTimeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"


class PullbackReason(str, Enum):
    SETUP_ARMED = "setup_armed"
    TRADE_PLANNED = "trade_planned"
    NEUTRAL_BIAS = "neutral_bias"
    INSUFFICIENT_BARS = "insufficient_bars"
    INVALID_ATR = "invalid_atr"
    NO_PULLBACK = "no_pullback"
    PULLBACK_TOO_SHALLOW = "pullback_too_shallow"
    PULLBACK_TOO_DEEP = "pullback_too_deep"
    NO_CONTINUATION = "no_continuation"
    TRIGGER_BODY_TOO_SMALL = "trigger_body_too_small"
    TRIGGER_AFTER_CUTOFF = "trigger_after_cutoff"
    SPREAD_TOO_WIDE = "spread_too_wide"
    STOP_TOO_CLOSE = "stop_too_close"
    STOP_TOO_FAR = "stop_too_far"
    BROKER_STOP_INVALID = "broker_stop_invalid"
    VOLUME_BELOW_MINIMUM = "volume_below_minimum"
    RISK_EXCEEDED = "risk_exceeded"
    MARGIN_EXCEEDED = "margin_exceeded"
    NEWS_BLOCKED = "news_blocked"
    EXISTING_EXPOSURE = "existing_exposure"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class ExitReason(str, Enum):
    TARGET_CLOSED = "target_closed"
    STOPPED = "stopped"
    MOMENTUM_ABORT = "momentum_abort"
    SPREAD_ABORT_BEFORE_ENTRY = "spread_abort_before_entry"
    ENTRY_TIMEOUT = "entry_timeout"
    SESSION_FLATTENED = "session_flattened"


def _aware(*values: pd.Timestamp) -> None:
    if any(value.tzinfo is None for value in values):
        raise ValueError("timestamps must be timezone-aware")


def _positive(name: str, *values: float) -> None:
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in values):
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class BiasDecision:
    direction: TradeDirection | None
    reason: PullbackReason
    session_start: pd.Timestamp
    h1_close: float
    h1_ema_now: float
    h1_ema_three_bars_ago: float
    m15_close: float
    m15_ema_now: float
    m15_ema_three_bars_ago: float

    def __post_init__(self) -> None:
        _aware(self.session_start)
        _positive(
            "bias values",
            self.h1_close,
            self.h1_ema_now,
            self.h1_ema_three_bars_ago,
            self.m15_close,
            self.m15_ema_now,
            self.m15_ema_three_bars_ago,
        )


@dataclass(frozen=True, slots=True)
class PullbackSetup:
    candidate: PullbackCandidate
    direction: TradeDirection
    atr: float
    pullback_swing: float
    pre_pullback_swing: float
    trigger_close_time: pd.Timestamp
    entry_available_time: pd.Timestamp
    trigger_close: float
    stop: float
    reference_spread: float

    def __post_init__(self) -> None:
        _aware(self.trigger_close_time, self.entry_available_time)
        _positive(
            "setup values",
            self.atr,
            self.pullback_swing,
            self.pre_pullback_swing,
            self.trigger_close,
            self.stop,
        )
        if not math.isfinite(self.reference_spread) or self.reference_spread < 0:
            raise ValueError("reference spread must be finite and nonnegative")
        if self.entry_available_time < self.trigger_close_time:
            raise ValueError("entry cannot be available before trigger close")
        if self.direction is TradeDirection.LONG and self.stop >= self.pullback_swing:
            raise ValueError("long stop must be below pullback swing")
        if self.direction is TradeDirection.SHORT and self.stop <= self.pullback_swing:
            raise ValueError("short stop must be after pullback swing")


@dataclass(frozen=True, slots=True)
class TradePlan:
    trade_id: str
    setup: PullbackSetup
    executable_entry: float
    target: float
    volume: float
    development_spread_ceiling: float
    projected_loss: float
    projected_margin: float
    starting_day_equity: float

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id must not be empty")
        _positive(
            "trade plan values",
            self.executable_entry,
            self.target,
            self.volume,
            self.projected_loss,
            self.starting_day_equity,
        )
        if self.projected_margin < 0 or self.development_spread_ceiling < 0:
            raise ValueError("margin and spread ceiling must be nonnegative")
        if self.setup.direction is TradeDirection.LONG and self.target <= self.executable_entry:
            raise ValueError("long target must be above entry")
        if self.setup.direction is TradeDirection.SHORT and self.target >= self.executable_entry:
            raise ValueError("short target must be below entry")


@dataclass(frozen=True, slots=True)
class TradeResult:
    plan: TradePlan
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    reason: ExitReason
    pnl_cash: float
    net_r: float
    spread_paid: float
    local_date: date

    def __post_init__(self) -> None:
        _aware(self.entry_time, self.exit_time)
        _positive("trade prices", self.entry_price, self.exit_price)
        if self.exit_time < self.entry_time:
            raise ValueError("exit cannot precede entry")
        if self.reason in {
            ExitReason.SPREAD_ABORT_BEFORE_ENTRY,
            ExitReason.ENTRY_TIMEOUT,
        }:
            raise ValueError("no-entry reason cannot create a trade result")
        if not all(math.isfinite(value) for value in (self.pnl_cash, self.net_r)):
            raise ValueError("trade returns must be finite")
        if not math.isfinite(self.spread_paid) or self.spread_paid < 0:
            raise ValueError("spread paid must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class SetupDecision:
    setup: PullbackSetup | None
    reason: PullbackReason


@dataclass(frozen=True, slots=True)
class PlanDecision:
    plan: TradePlan | None
    reason: PullbackReason


@dataclass(frozen=True, slots=True)
class SimulationResult:
    trade: TradeResult | None
    reason: ExitReason

    def __post_init__(self) -> None:
        no_entry = {
            ExitReason.SPREAD_ABORT_BEFORE_ENTRY,
            ExitReason.ENTRY_TIMEOUT,
        }
        if self.trade is None and self.reason not in no_entry:
            raise ValueError("trade result is required for a closing exit reason")
        if self.trade is not None and self.trade.reason is not self.reason:
            raise ValueError("simulation and trade exit reasons must match")
