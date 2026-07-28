from __future__ import annotations

import math

import pandas as pd

from .indicators import atr, ema
from .models import (
    Direction,
    LevelSide,
    LiquidityLevel,
    ReasonCode,
    SignalDecision,
    StrategyContext,
)


def _completed(
    bars: pd.DataFrame, as_of: pd.Timestamp, minutes: int
) -> pd.DataFrame:
    if bars.index.tz is None or as_of.tzinfo is None:
        raise ValueError("strategy timestamps must be timezone-aware")
    cutoff = as_of.tz_convert("UTC")
    utc = bars.copy()
    utc.index = utc.index.tz_convert("UTC")
    return utc.loc[utc.index + pd.Timedelta(minutes=minutes) <= cutoff]


def _m15_direction(bars: pd.DataFrame, period: int) -> Direction | None:
    if len(bars) < period + 3:
        return None
    average = ema(bars["close"], period)
    if pd.isna(average.iloc[-1]) or pd.isna(average.iloc[-4]):
        return None
    latest = bars.iloc[-1]
    previous = bars.iloc[-2]
    bullish = (
        latest["close"] > average.iloc[-1]
        and average.iloc[-1] > average.iloc[-4]
        and latest["high"] > previous["high"]
        and latest["low"] > previous["low"]
    )
    bearish = (
        latest["close"] < average.iloc[-1]
        and average.iloc[-1] < average.iloc[-4]
        and latest["high"] < previous["high"]
        and latest["low"] < previous["low"]
    )
    if bullish:
        return Direction.LONG
    if bearish:
        return Direction.SHORT
    return None


def _decision(
    reasons: tuple[ReasonCode, ...],
    *,
    direction: Direction | None = None,
    signal_time: pd.Timestamp | None = None,
    entry: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    level: LiquidityLevel | None = None,
    diagnostics: dict[str, object] | None = None,
) -> SignalDecision:
    return SignalDecision(
        eligible=reasons[-1] is ReasonCode.QUALIFIED,
        direction=direction,
        signal_time=signal_time,
        entry=entry,
        stop=stop,
        target=target,
        reasons=reasons,
        level_name=None if level is None else level.name,
        diagnostics=tuple(sorted((diagnostics or {}).items())),
    )


def _crossed_and_closed_beyond(
    bar: pd.Series, level: LiquidityLevel, direction: Direction
) -> bool:
    if direction is Direction.LONG:
        return bar["low"] < level.price and bar["close"] <= level.price
    return bar["high"] > level.price and bar["close"] >= level.price


def _penetration(
    bar: pd.Series, level: LiquidityLevel, direction: Direction
) -> float:
    if direction is Direction.LONG:
        return level.price - float(bar["low"])
    return float(bar["high"]) - level.price


def _reclaimed(
    bar: pd.Series, level: LiquidityLevel, direction: Direction
) -> bool:
    if direction is Direction.LONG:
        return bar["close"] > level.price
    return bar["close"] < level.price


def _has_displacement(
    bars: pd.DataFrame,
    index: int,
    direction: Direction,
    current_atr: float,
    threshold: float,
) -> bool:
    bar = bars.iloc[index]
    if index < 3 or not math.isfinite(current_atr) or current_atr <= 0:
        return False
    previous = bars.iloc[index - 3 : index]
    if direction is Direction.LONG:
        body = float(bar["close"] - bar["open"])
        return body >= threshold * current_atr and bar["close"] > previous["high"].max()
    body = float(bar["open"] - bar["close"])
    return body >= threshold * current_atr and bar["close"] < previous["low"].min()


def _retest_touched(
    bar: pd.Series,
    displacement: pd.Series,
    level: LiquidityLevel,
    direction: Direction,
    sweep_extreme: float,
) -> bool:
    if direction is Direction.LONG:
        body = float(displacement["close"] - displacement["open"])
        zone_low = float(displacement["open"] + 0.25 * body)
        zone_high = float(displacement["open"] + 0.50 * body)
        zone_touch = bar["low"] <= zone_high and bar["high"] >= zone_low
        level_touch = bar["low"] <= level.price <= bar["high"]
        return bool((zone_touch or level_touch) and bar["close"] > sweep_extreme)
    body = float(displacement["open"] - displacement["close"])
    zone_low = float(displacement["close"] + 0.50 * body)
    zone_high = float(displacement["close"] + 0.75 * body)
    zone_touch = bar["low"] <= zone_high and bar["high"] >= zone_low
    level_touch = bar["low"] <= level.price <= bar["high"]
    return bool((zone_touch or level_touch) and bar["close"] < sweep_extreme)


def _opposing_price(
    levels: tuple[LiquidityLevel, ...], direction: Direction, entry: float
) -> float | None:
    if direction is Direction.LONG:
        prices = [level.price for level in levels if level.side is LevelSide.HIGH and level.price > entry]
        return min(prices) if prices else None
    prices = [level.price for level in levels if level.side is LevelSide.LOW and level.price < entry]
    return max(prices) if prices else None


def evaluate_setup(context: StrategyContext) -> SignalDecision:
    effective_as_of = min(context.as_of, context.session_end)
    m15 = _completed(context.m15, effective_as_of, 15)
    m5 = _completed(context.m5, effective_as_of, 5)
    direction = _m15_direction(m15, context.config.ema_period)
    if direction is None:
        return _decision((ReasonCode.NEUTRAL_M15,))
    if len(m5) < context.config.atr_period + 3:
        return _decision((ReasonCode.NO_LEVEL_SWEEP,), direction=direction)

    volatility = atr(m5, context.config.atr_period)
    desired_side = LevelSide.LOW if direction is Direction.LONG else LevelSide.HIGH
    levels = tuple(level for level in context.levels if level.side is desired_side)
    if not levels:
        return _decision((ReasonCode.NO_LEVEL_SWEEP,), direction=direction)

    candidate: tuple[int, LiquidityLevel, float, float, bool] | None = None
    threshold_rejection: tuple[ReasonCode, int, LiquidityLevel, float] | None = None
    for index in range(len(m5) - 1, context.config.atr_period - 2, -1):
        if not context.session_start <= m5.index[index] < context.session_end:
            continue
        bar = m5.iloc[index]
        current_atr = float(volatility.iloc[index])
        if not math.isfinite(current_atr) or current_atr <= 0:
            continue
        for level in levels:
            same_bar_reclaimed = _reclaimed(bar, level, direction)
            if same_bar_reclaimed:
                crossed = (
                    bar["low"] < level.price
                    if direction is Direction.LONG
                    else bar["high"] > level.price
                )
                if not crossed or not context.config.allow_same_bar_reclaim:
                    continue
            elif not _crossed_and_closed_beyond(bar, level, direction):
                continue
            normalized = _penetration(bar, level, direction) / current_atr
            if normalized < context.config.sweep_atr_min:
                threshold_rejection = (ReasonCode.SWEEP_TOO_SMALL, index, level, normalized)
                break
            if normalized > context.config.sweep_atr_max:
                threshold_rejection = (ReasonCode.SWEEP_TOO_DEEP, index, level, normalized)
                break
            extreme = float(bar["low"] if direction is Direction.LONG else bar["high"])
            candidate = (index, level, extreme, normalized, same_bar_reclaimed)
            break
        if candidate is not None or threshold_rejection is not None:
            break

    if candidate is None:
        if threshold_rejection is not None:
            reason, index, level, normalized = threshold_rejection
            return _decision(
                (reason,),
                direction=direction,
                signal_time=m5.index[index],
                level=level,
                diagnostics={"sweep_atr": normalized},
            )
        return _decision((ReasonCode.NO_LEVEL_SWEEP,), direction=direction)

    sweep_index, level, sweep_extreme, normalized, same_bar_reclaimed = candidate
    positive = (ReasonCode.SWEEP_DETECTED,)
    reclaim_index = next(
        (
            index
            for index in range(
                sweep_index if same_bar_reclaimed else sweep_index + 1,
                min(sweep_index + 3, len(m5)),
            )
            if _reclaimed(m5.iloc[index], level, direction)
        ),
        None,
    )
    if reclaim_index is None:
        return _decision(
            positive + (ReasonCode.NO_RECLAIM,),
            direction=direction,
            signal_time=m5.index[sweep_index],
            level=level,
            diagnostics={"sweep_atr": normalized},
        )

    positive += (ReasonCode.RECLAIMED,)
    displacement_index = next(
        (
            index
            for index in range(reclaim_index, min(reclaim_index + 2, len(m5)))
            if _has_displacement(
                m5,
                index,
                direction,
                float(volatility.iloc[index]),
                context.config.displacement_atr_min,
            )
        ),
        None,
    )
    if displacement_index is None:
        return _decision(
            positive + (ReasonCode.WEAK_DISPLACEMENT,),
            direction=direction,
            signal_time=m5.index[reclaim_index],
            level=level,
        )

    positive += (ReasonCode.DISPLACED,)
    retest_index = next(
        (
            index
            for index in range(displacement_index + 1, min(displacement_index + 4, len(m5)))
            if _retest_touched(
                m5.iloc[index],
                m5.iloc[displacement_index],
                level,
                direction,
                sweep_extreme,
            )
        ),
        None,
    )
    if retest_index is None:
        return _decision(
            positive + (ReasonCode.NO_RETEST,),
            direction=direction,
            signal_time=m5.index[displacement_index],
            level=level,
        )

    positive += (ReasonCode.RETESTED,)
    retest = m5.iloc[retest_index]
    entry = float(retest["close"] + context.spread) if direction is Direction.LONG else float(retest["close"])
    stop = sweep_extreme - context.spread if direction is Direction.LONG else sweep_extreme + context.spread
    risk = abs(entry - stop)
    current_atr = float(volatility.iloc[retest_index])
    stop_atr = risk / current_atr
    if stop_atr > context.config.max_stop_atr:
        return _decision(
            positive + (ReasonCode.STOP_TOO_WIDE,),
            direction=direction,
            signal_time=m5.index[retest_index],
            entry=entry,
            stop=stop,
            level=level,
            diagnostics={"stop_atr": stop_atr},
        )

    opposing = _opposing_price(context.levels, direction, entry)
    room_r = 0.0 if opposing is None else abs(opposing - entry) / risk
    if opposing is None or room_r < context.config.minimum_room_r:
        return _decision(
            positive + (ReasonCode.INSUFFICIENT_ROOM,),
            direction=direction,
            signal_time=m5.index[retest_index],
            entry=entry,
            stop=stop,
            level=level,
            diagnostics={"room_r": room_r},
        )

    if direction is Direction.LONG:
        target = min(entry + context.config.target_r * risk, opposing)
    else:
        target = max(entry - context.config.target_r * risk, opposing)
    return _decision(
        positive + (ReasonCode.QUALIFIED,),
        direction=direction,
        signal_time=m5.index[retest_index],
        entry=entry,
        stop=float(stop),
        target=float(target),
        level=level,
        diagnostics={"room_r": room_r, "stop_atr": stop_atr, "sweep_atr": normalized},
    )
