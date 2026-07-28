from __future__ import annotations

import math

import pandas as pd

from gscalp.grid_config import GridConfig
from gscalp.grid_models import BiasDecision, BiasDirection, GeometryDecision, GridGeometry, GridReason
from gscalp.mt5_read import SymbolSpec


def round_entry(price: float, direction: BiasDirection, tick_size: float) -> float:
    units = price / tick_size
    rounded = math.floor(units) if direction is BiasDirection.LONG else math.ceil(units)
    return rounded * tick_size


def round_stop(price: float, direction: BiasDirection, tick_size: float) -> float:
    units = price / tick_size
    rounded = math.floor(units) if direction is BiasDirection.LONG else math.ceil(units)
    return rounded * tick_size


def _broker_distances_are_valid(
    anchor: float, stop: float, levels: tuple[float, float, float], symbol: SymbolSpec
) -> bool:
    minimum_distance = symbol.stops_level * symbol.point
    return (
        abs(anchor - stop) >= minimum_distance
        and all(abs(anchor - level) >= minimum_distance for level in levels)
        and all(abs(level - stop) >= minimum_distance for level in levels)
    )


def build_grid_geometry(
    *,
    bias: BiasDecision,
    session_start: pd.Timestamp,
    anchor_bid: float,
    anchor_ask: float,
    atr: float | None,
    reference_spread: float | None,
    current_spread: float,
    spread_ceiling: float,
    pivot: tuple[pd.Timestamp, float] | None,
    symbol: SymbolSpec,
    config: GridConfig,
) -> GeometryDecision:
    if bias.direction is None:
        return GeometryDecision(None, GridReason.NEUTRAL_BIAS)
    if atr is None or not math.isfinite(atr) or atr <= 0:
        return GeometryDecision(None, GridReason.ATR_UNAVAILABLE)
    if pivot is None or reference_spread is None:
        return GeometryDecision(None, GridReason.NO_CONFIRMED_PIVOT)

    direction = bias.direction
    anchor = anchor_ask if direction is BiasDirection.LONG else anchor_bid
    buffer = max(
        config.stop_buffer_atr * atr,
        config.stop_buffer_spread_multiple * reference_spread,
    )
    raw_stop = pivot[1] - buffer if direction is BiasDirection.LONG else pivot[1] + buffer
    stop = round_stop(raw_stop, direction, symbol.tick_size)
    distance = abs(anchor - stop)
    if distance < config.invalidation_atr_min * atr:
        return GeometryDecision(None, GridReason.INVALIDATION_TOO_CLOSE)
    if distance > config.invalidation_atr_max * atr:
        return GeometryDecision(None, GridReason.INVALIDATION_TOO_FAR)
    if current_spread > spread_ceiling:
        return GeometryDecision(None, GridReason.SPREAD_TOO_WIDE)

    sign = -1.0 if direction is BiasDirection.LONG else 1.0
    levels = tuple(
        round_entry(anchor + sign * fraction * distance, direction, symbol.tick_size)
        for fraction in config.level_fractions
    )
    profit_distance = max(
        config.profit_distance_fraction * distance,
        config.reference_spread_multiple * reference_spread,
        config.current_spread_multiple * current_spread,
    )
    if profit_distance > config.profit_distance_max_fraction * distance:
        return GeometryDecision(None, GridReason.SPREAD_TOO_WIDE)
    if not _broker_distances_are_valid(anchor, stop, levels, symbol):
        return GeometryDecision(None, GridReason.BROKER_DISTANCE_INVALID)

    return GeometryDecision(
        GridGeometry(
            direction,
            session_start,
            session_start + pd.Timedelta(minutes=config.session_minutes),
            anchor,
            stop,
            atr,
            reference_spread,
            current_spread,
            profit_distance,
            levels,
        ),
        GridReason.GRID_ARMED,
    )


def basket_target(
    direction: BiasDirection,
    fills: tuple[tuple[float, float], ...],
    profit_distance: float,
    tick_size: float,
) -> float:
    weighted = sum(price * volume for price, volume in fills) / sum(
        volume for _, volume in fills
    )
    raw = weighted + profit_distance if direction is BiasDirection.LONG else weighted - profit_distance
    units = raw / tick_size
    conservative = math.floor(units) if direction is BiasDirection.LONG else math.ceil(units)
    return round(conservative * tick_size, 10)
