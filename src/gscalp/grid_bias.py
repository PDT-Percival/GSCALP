from __future__ import annotations

import pandas as pd

from gscalp.grid_config import GridConfig
from gscalp.grid_models import BiasDecision, BiasDirection, GridReason
from gscalp.indicators import ema


def completed_bars(
    bars: pd.DataFrame, as_of: pd.Timestamp, timeframe_minutes: int
) -> pd.DataFrame:
    if bars.index.tz is None or as_of.tzinfo is None:
        raise ValueError("bars and as_of must be timezone-aware")
    utc = bars.copy()
    utc.index = utc.index.tz_convert("UTC")
    cutoff = as_of.tz_convert("UTC")
    return utc.loc[utc.index + pd.Timedelta(minutes=timeframe_minutes) <= cutoff]


def evaluate_locked_bias(
    m15: pd.DataFrame, as_of: pd.Timestamp, config: GridConfig
) -> BiasDecision:
    bars = completed_bars(m15, as_of, 15)
    average = ema(bars["close"], config.ema_period)
    if len(bars) < config.ema_period + 3 or pd.isna(average.iloc[-1]):
        return BiasDecision(None, GridReason.NEUTRAL_BIAS, as_of, None, None)
    latest, previous = bars.iloc[-1], bars.iloc[-2]
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
    direction = BiasDirection.LONG if bullish else BiasDirection.SHORT if bearish else None
    reason = GridReason.BIAS_LOCKED if direction else GridReason.NEUTRAL_BIAS
    return BiasDecision(
        direction, reason, as_of, float(average.iloc[-1]), float(average.iloc[-4])
    )


def confirmed_pivot(
    m5: pd.DataFrame,
    as_of: pd.Timestamp,
    direction: BiasDirection,
    config: GridConfig,
) -> tuple[pd.Timestamp, float] | None:
    bars = completed_bars(m5, as_of, 5).tail(config.pivot_lookback)
    for index in range(
        len(bars) - config.pivot_right - 1, config.pivot_left - 1, -1
    ):
        row = bars.iloc[index]
        left = bars.iloc[index - config.pivot_left : index]
        right = bars.iloc[index + 1 : index + config.pivot_right + 1]
        if direction is BiasDirection.LONG:
            confirmed = (
                row["low"] < left["low"].min() and row["low"] < right["low"].min()
            )
            price = float(row["low"])
        else:
            confirmed = (
                row["high"] > left["high"].max()
                and row["high"] > right["high"].max()
            )
            price = float(row["high"])
        if confirmed:
            return bars.index[index], price
    return None
