from __future__ import annotations

import pandas as pd

from .pullback_config import PullbackConfig
from .pullback_models import BiasDecision, PullbackReason, TradeDirection


def completed_before(
    bars: pd.DataFrame,
    available_at: pd.Timestamp,
    *,
    timeframe_minutes: int,
) -> pd.DataFrame:
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars must have a DatetimeIndex")
    if bars.index.tz is None or available_at.tzinfo is None:
        raise ValueError("bars and available_at must be timezone-aware")
    if timeframe_minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    utc = bars.copy()
    utc.index = utc.index.tz_convert("UTC")
    cutoff = available_at.tz_convert("UTC")
    duration = pd.Timedelta(minutes=timeframe_minutes)
    return utc.loc[utc.index + duration <= cutoff]


def _values(
    bars: pd.DataFrame,
    *,
    period: int,
    slope_bars: int,
) -> tuple[float, float, float]:
    average = bars["close"].astype(float).ewm(span=period, adjust=False).mean()
    return (
        float(bars["close"].iloc[-1]),
        float(average.iloc[-1]),
        float(average.iloc[-(slope_bars + 1)]),
    )


def evaluate_locked_bias(
    h1: pd.DataFrame,
    m15: pd.DataFrame,
    session_start: pd.Timestamp,
    config: PullbackConfig,
) -> BiasDecision:
    h1_complete = completed_before(h1, session_start, timeframe_minutes=60)
    m15_complete = completed_before(m15, session_start, timeframe_minutes=15)
    required = config.bias_ema_period + config.bias_slope_bars
    if len(h1_complete) < required or len(m15_complete) < required:
        return BiasDecision(
            None,
            PullbackReason.INSUFFICIENT_BARS,
            session_start,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    h1_close, h1_now, h1_prior = _values(
        h1_complete,
        period=config.bias_ema_period,
        slope_bars=config.bias_slope_bars,
    )
    m15_close, m15_now, m15_prior = _values(
        m15_complete,
        period=config.bias_ema_period,
        slope_bars=config.bias_slope_bars,
    )
    bullish = (
        h1_close > h1_now > h1_prior
        and m15_close > m15_now > m15_prior
    )
    bearish = (
        h1_close < h1_now < h1_prior
        and m15_close < m15_now < m15_prior
    )
    direction = (
        TradeDirection.LONG
        if bullish
        else TradeDirection.SHORT
        if bearish
        else None
    )
    reason = PullbackReason.SETUP_ARMED if direction else PullbackReason.NEUTRAL_BIAS
    return BiasDecision(
        direction,
        reason,
        session_start,
        h1_close,
        h1_now,
        h1_prior,
        m15_close,
        m15_now,
        m15_prior,
    )
