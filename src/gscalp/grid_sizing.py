from __future__ import annotations

import math
from typing import Any, Protocol

from gscalp.grid_config import GridConfig
from gscalp.grid_geometry import basket_target
from gscalp.grid_models import (
    BiasDirection,
    GridGeometry,
    GridLevelPlan,
    GridPlan,
    GridReason,
    PlanDecision,
)
from gscalp.mt5_read import SymbolSpec


class ProfitMarginCalculator(Protocol):
    def loss_for_one_lot(
        self, direction: BiasDirection, entry: float, stop: float
    ) -> float:
        raise NotImplementedError

    def margin_for_volume(
        self, direction: BiasDirection, volume: float, entry: float
    ) -> float:
        raise NotImplementedError


class MT5ProfitMarginCalculator:
    """Read-only bridge for MT5 profit and margin calculations."""

    def __init__(self, mt5_module: Any, symbol: str) -> None:
        self._mt5 = mt5_module
        self._symbol = symbol

    def _order_type(self, direction: BiasDirection) -> int:
        return (
            self._mt5.ORDER_TYPE_BUY
            if direction is BiasDirection.LONG
            else self._mt5.ORDER_TYPE_SELL
        )

    def loss_for_one_lot(
        self, direction: BiasDirection, entry: float, stop: float
    ) -> float | None:
        return self._mt5.order_calc_profit(
            self._order_type(direction), self._symbol, 1.0, entry, stop
        )

    def margin_for_volume(
        self, direction: BiasDirection, volume: float, entry: float
    ) -> float | None:
        return self._mt5.order_calc_margin(
            self._order_type(direction), self._symbol, volume, entry
        )


def floor_volume(raw: float, step: float) -> float:
    return math.floor(raw / step + 1e-12) * step


def _positive_finite(value: object) -> float | None:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def size_grid(
    *,
    geometry: GridGeometry,
    starting_day_equity: float,
    free_margin: float,
    symbol: SymbolSpec,
    calculator: ProfitMarginCalculator,
    config: GridConfig,
    basket_id: str,
) -> PlanDecision:
    losses = tuple(
        _positive_finite(
            calculator.loss_for_one_lot(geometry.direction, entry, geometry.stop)
        )
        for entry in geometry.level_prices
    )
    if any(loss is None for loss in losses):
        return PlanDecision(None, GridReason.BASKET_RISK_EXCEEDED)
    valid_losses = tuple(loss for loss in losses if loss is not None)
    nominal_cash = starting_day_equity * config.nominal_risk_fraction
    volume = floor_volume(nominal_cash / sum(valid_losses), symbol.volume_step)
    if volume < symbol.volume_min:
        return PlanDecision(None, GridReason.VOLUME_BELOW_MINIMUM)
    projected_loss = sum(valid_losses) * volume
    absolute_cap = starting_day_equity * config.absolute_risk_fraction
    if projected_loss > absolute_cap:
        return PlanDecision(None, GridReason.BASKET_RISK_EXCEEDED)
    margins = tuple(
        calculator.margin_for_volume(geometry.direction, volume, entry)
        for entry in geometry.level_prices
    )
    try:
        total_margin = sum(float(margin) for margin in margins)
    except (TypeError, ValueError):
        return PlanDecision(None, GridReason.MARGIN_LIMIT_EXCEEDED)
    if not math.isfinite(total_margin) or total_margin > free_margin * config.max_margin_fraction:
        return PlanDecision(None, GridReason.MARGIN_LIMIT_EXCEEDED)
    levels = tuple(
        GridLevelPlan(
            number,
            entry,
            volume,
            geometry.stop,
            basket_target(
                geometry.direction,
                ((entry, volume),),
                geometry.profit_distance,
                symbol.tick_size,
            ),
        )
        for number, entry in enumerate(geometry.level_prices, start=1)
    )
    return PlanDecision(
        GridPlan(basket_id, geometry, levels, projected_loss, total_margin),
        GridReason.GRID_ARMED,
    )
