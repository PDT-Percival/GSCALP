from __future__ import annotations

import math

import pandas as pd

from .indicators import atr as _atr
from .indicators import ema
from .pullback_bias import completed_before
from .pullback_config import PullbackCandidate, PullbackConfig
from .pullback_models import (
    BiasDecision,
    PullbackReason,
    PullbackSetup,
    SetupDecision,
    TradeDirection,
)


_OHLC = ("open", "high", "low", "close")


def atr(bars: pd.DataFrame, period: int) -> pd.Series:
    return _atr(bars, period)


def _validate_bars(name: str, bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError(f"{name} bars must have a timezone-aware DatetimeIndex")
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError(f"{name} bars must be sorted and unique")
    missing = sorted(set(_OHLC) - set(bars.columns))
    if missing:
        raise ValueError(f"{name} bars missing columns: {', '.join(missing)}")
    result = bars.loc[:, _OHLC].astype(float).copy()
    result.index = result.index.tz_convert("UTC")
    return result


def _recent_breakout_level(
    bars: pd.DataFrame,
    through: pd.Timestamp,
    direction: TradeDirection,
) -> float | None:
    eligible = bars.loc[bars.index <= through]
    if len(eligible) < 2:
        return None
    levels: list[float] = []
    for position in range(1, len(eligible)):
        current = eligible.iloc[position]
        previous = eligible.iloc[position - 1]
        if direction is TradeDirection.LONG and current["close"] > previous["high"]:
            levels.append(float(current["close"]))
        if direction is TradeDirection.SHORT and current["close"] < previous["low"]:
            levels.append(float(current["close"]))
    return levels[-1] if levels else None


def _pullback_geometry(
    m5: pd.DataFrame,
    trigger_open: pd.Timestamp,
    session_start: pd.Timestamp,
    direction: TradeDirection,
    reference_spread: float,
    config: PullbackConfig,
) -> tuple[PullbackReason, tuple[float, float, float, float] | None]:
    history = completed_before(m5, trigger_open, timeframe_minutes=5)
    average_range = atr(history, config.atr_period)
    if average_range.empty or pd.isna(average_range.iloc[-1]):
        return PullbackReason.INVALID_ATR, None
    atr_value = float(average_range.iloc[-1])
    if not math.isfinite(atr_value) or atr_value <= 0:
        return PullbackReason.INVALID_ATR, None

    active = history.loc[history.index >= session_start]
    if len(active) < 2:
        return PullbackReason.NO_PULLBACK, None
    if direction is TradeDirection.LONG:
        pre_index = active["high"].idxmax()
        pre_swing = float(active.loc[pre_index, "high"])
    else:
        pre_index = active["low"].idxmin()
        pre_swing = float(active.loc[pre_index, "low"])
    retracement = active.loc[active.index > pre_index]
    if retracement.empty:
        return PullbackReason.NO_PULLBACK, None
    if direction is TradeDirection.LONG:
        pullback_index = retracement["low"].idxmin()
        pullback_swing = float(retracement.loc[pullback_index, "low"])
        distance = pre_swing - pullback_swing
    else:
        pullback_index = retracement["high"].idxmax()
        pullback_swing = float(retracement.loc[pullback_index, "high"])
        distance = pullback_swing - pre_swing

    average = ema(history["close"], config.bias_ema_period)
    ema_value = average.loc[pullback_index]
    breakout = _recent_breakout_level(history, pre_index, direction)
    if pd.isna(ema_value) and breakout is None:
        return PullbackReason.NO_PULLBACK, None
    zone_values = [float(value) for value in (ema_value, breakout) if value is not None and not pd.isna(value)]
    zone_low, zone_high = min(zone_values), max(zone_values)
    pullback_bar = history.loc[pullback_index]
    touches_zone = float(pullback_bar["low"]) <= zone_high and float(pullback_bar["high"]) >= zone_low
    if not touches_zone:
        return PullbackReason.NO_PULLBACK, None

    distance_atr = distance / atr_value
    if distance_atr < config.pullback_atr_min:
        return PullbackReason.PULLBACK_TOO_SHALLOW, None
    if distance_atr > config.pullback_atr_max:
        return PullbackReason.PULLBACK_TOO_DEEP, None
    buffer = max(
        config.stop_buffer_atr * atr_value,
        config.stop_buffer_spread_multiple * reference_spread,
    )
    stop = (
        pullback_swing - buffer
        if direction is TradeDirection.LONG
        else pullback_swing + buffer
    )
    return PullbackReason.SETUP_ARMED, (atr_value, pullback_swing, pre_swing, stop)


def detect_pullback_setup(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    bias: BiasDecision,
    candidate: PullbackCandidate,
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
    reference_spread: float,
    config: PullbackConfig,
) -> SetupDecision:
    if session_start.tzinfo is None or session_end.tzinfo is None:
        raise ValueError("session bounds must be timezone-aware")
    if session_end <= session_start:
        raise ValueError("session_end must be after session_start")
    if not math.isfinite(reference_spread) or reference_spread < 0:
        raise ValueError("reference spread must be finite and nonnegative")
    if bias.direction is None:
        return SetupDecision(None, bias.reason)
    one_minute = _validate_bars("M1", m1)
    five_minute = _validate_bars("M5", m5)
    trigger_bars = one_minute if candidate.trigger_timeframe == "M1" else five_minute
    timeframe_minutes = 1 if candidate.trigger_timeframe == "M1" else 5
    duration = pd.Timedelta(minutes=timeframe_minutes)
    start = session_start.tz_convert("UTC")
    end = session_end.tz_convert("UTC")
    cutoff = start + pd.Timedelta(minutes=config.entry_cutoff_minute)
    averages = ema(trigger_bars["close"], config.trigger_ema_period)
    last_geometry_reason = PullbackReason.NO_PULLBACK
    saw_small_body = False
    saw_late_trigger = False

    for position in range(1, len(trigger_bars)):
        trigger_open = trigger_bars.index[position]
        trigger_close_time = trigger_open + duration
        if trigger_open < start or trigger_close_time >= end:
            continue
        geometry_reason, geometry = _pullback_geometry(
            five_minute,
            trigger_open,
            start,
            bias.direction,
            reference_spread,
            config,
        )
        last_geometry_reason = geometry_reason
        if geometry is None:
            continue
        row = trigger_bars.iloc[position]
        previous = trigger_bars.iloc[position - 1]
        candle_range = float(row["high"] - row["low"])
        body_fraction = (
            abs(float(row["close"] - row["open"])) / candle_range
            if candle_range > 0
            else 0.0
        )
        continuation = (
            float(row["close"]) > float(previous["high"])
            and float(row["close"]) > float(averages.iloc[position])
            if bias.direction is TradeDirection.LONG
            else float(row["close"]) < float(previous["low"])
            and float(row["close"]) < float(averages.iloc[position])
        )
        if not continuation:
            continue
        if body_fraction < config.trigger_body_fraction_min:
            saw_small_body = True
            continue
        if trigger_close_time > cutoff:
            saw_late_trigger = True
            continue
        atr_value, pullback_swing, pre_swing, stop = geometry
        return SetupDecision(
            PullbackSetup(
                candidate,
                bias.direction,
                atr_value,
                pullback_swing,
                pre_swing,
                trigger_close_time,
                trigger_close_time,
                float(row["close"]),
                stop,
                reference_spread,
            ),
            PullbackReason.SETUP_ARMED,
        )

    if saw_late_trigger:
        reason = PullbackReason.TRIGGER_AFTER_CUTOFF
    elif saw_small_body:
        reason = PullbackReason.TRIGGER_BODY_TOO_SMALL
    elif last_geometry_reason is not PullbackReason.SETUP_ARMED:
        reason = last_geometry_reason
    else:
        reason = PullbackReason.NO_CONTINUATION
    return SetupDecision(None, reason)
