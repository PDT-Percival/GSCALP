from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

import pandas as pd


def ema(values: pd.Series, period: int) -> pd.Series:
    if period < 2:
        raise ValueError("EMA period must be at least two")
    return values.astype(float).ewm(
        span=period, adjust=False, min_periods=period
    ).mean()


def true_range(bars: pd.DataFrame) -> pd.Series:
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    previous_close = bars["close"].astype(float).shift(1)
    ranges = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(bars: pd.DataFrame, period: int) -> pd.Series:
    if period < 2:
        raise ValueError("ATR period must be at least two")
    return true_range(bars).ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()


def session_high_low(
    bars: pd.DataFrame,
    *,
    local_date: str | date,
    start: time,
    end: time,
    timezone_name: str,
) -> tuple[float, float]:
    if bars.index.tz is None:
        raise ValueError("bar index must be timezone-aware")
    target_date = (
        date.fromisoformat(local_date) if isinstance(local_date, str) else local_date
    )
    local = bars.copy()
    local.index = local.index.tz_convert(ZoneInfo(timezone_name))
    mask = [
        stamp.date() == target_date and start <= stamp.time().replace(tzinfo=None) < end
        for stamp in local.index
    ]
    selected = local.loc[mask]
    if selected.empty:
        raise ValueError("no bars in requested session")
    return float(selected["high"].max()), float(selected["low"].min())
