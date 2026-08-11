from __future__ import annotations

import math
from dataclasses import replace
from typing import Protocol

from .mt5_read import SymbolSpec
from .pullback_config import PullbackConfig
from .pullback_models import (
    PlanDecision,
    PullbackReason,
    PullbackSetup,
    TradeDirection,
    TradePlan,
)


class ProfitMarginCalculator(Protocol):
    def loss_for_one_lot(
        self,
        direction: TradeDirection,
        entry: float,
        stop: float,
    ) -> float | None: ...

    def margin_for_volume(
        self,
        direction: TradeDirection,
        volume: float,
        entry: float,
    ) -> float | None: ...


def floor_volume(raw: float, step: float) -> float:
    if not math.isfinite(raw) or raw < 0 or not math.isfinite(step) or step <= 0:
        raise ValueError("volume and step must be finite and valid")
    return math.floor(raw / step + 1e-12) * step


def _floor_price(price: float, tick_size: float) -> float:
    return math.floor(price / tick_size + 1e-12) * tick_size


def _ceil_price(price: float, tick_size: float) -> float:
    return math.ceil(price / tick_size - 1e-12) * tick_size


def _positive_finite(value: object) -> float | None:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def size_trade(
    *,
    setup: PullbackSetup,
    executable_entry: float,
    development_spread_ceiling: float,
    starting_day_equity: float,
    free_margin: float,
    symbol: SymbolSpec,
    calculator: ProfitMarginCalculator,
    config: PullbackConfig,
    trade_id: str,
) -> PlanDecision:
    contract_values = (
        executable_entry,
        starting_day_equity,
        free_margin,
        symbol.point,
        symbol.tick_size,
        symbol.volume_min,
        symbol.volume_step,
    )
    if any(not math.isfinite(value) or value <= 0 for value in contract_values):
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)
    if not math.isfinite(symbol.volume_max) or symbol.volume_max <= 0:
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)
    if development_spread_ceiling < 0 or not math.isfinite(development_spread_ceiling):
        return PlanDecision(None, PullbackReason.SPREAD_TOO_WIDE)

    if setup.direction is TradeDirection.LONG:
        rounded_stop = _floor_price(setup.stop, symbol.tick_size)
        distance = executable_entry - rounded_stop
    else:
        rounded_stop = _ceil_price(setup.stop, symbol.tick_size)
        distance = rounded_stop - executable_entry
    distance_atr = distance / setup.atr
    if distance_atr < config.stop_atr_min:
        return PlanDecision(None, PullbackReason.STOP_TOO_CLOSE)
    if distance_atr > config.stop_atr_max:
        return PlanDecision(None, PullbackReason.STOP_TOO_FAR)
    if distance < symbol.stops_level * symbol.point:
        return PlanDecision(None, PullbackReason.BROKER_STOP_INVALID)

    loss_for_one_lot = _positive_finite(
        calculator.loss_for_one_lot(
            setup.direction,
            executable_entry,
            rounded_stop,
        )
    )
    if loss_for_one_lot is None:
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)
    nominal_cash = starting_day_equity * config.nominal_risk_fraction
    volume = floor_volume(nominal_cash / loss_for_one_lot, symbol.volume_step)
    if volume < symbol.volume_min:
        return PlanDecision(None, PullbackReason.VOLUME_BELOW_MINIMUM)
    if volume > symbol.volume_max:
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)
    steps = volume / symbol.volume_step
    if not math.isclose(steps, round(steps), abs_tol=1e-9):
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)

    reserve = starting_day_equity * config.risk_reserve_fraction
    projected_loss = loss_for_one_lot * volume + reserve
    if projected_loss > starting_day_equity * config.absolute_risk_fraction + 1e-12:
        return PlanDecision(None, PullbackReason.RISK_EXCEEDED)
    try:
        projected_margin = float(
            calculator.margin_for_volume(
                setup.direction,
                volume,
                executable_entry,
            )
        )
    except (TypeError, ValueError):
        return PlanDecision(None, PullbackReason.MARGIN_EXCEEDED)
    if (
        not math.isfinite(projected_margin)
        or projected_margin < 0
        or projected_margin > free_margin * config.max_margin_fraction
    ):
        return PlanDecision(None, PullbackReason.MARGIN_EXCEEDED)

    ideal_target = (
        executable_entry + distance * setup.candidate.target_r
        if setup.direction is TradeDirection.LONG
        else executable_entry - distance * setup.candidate.target_r
    )
    target = (
        _floor_price(ideal_target, symbol.tick_size)
        if setup.direction is TradeDirection.LONG
        else _ceil_price(ideal_target, symbol.tick_size)
    )
    rounded_setup = replace(setup, stop=rounded_stop)
    return PlanDecision(
        TradePlan(
            trade_id,
            rounded_setup,
            executable_entry,
            target,
            volume,
            development_spread_ceiling,
            projected_loss,
            projected_margin,
            starting_day_equity,
        ),
        PullbackReason.TRADE_PLANNED,
    )
