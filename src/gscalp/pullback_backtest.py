from __future__ import annotations

import math
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from .indicators import ema
from .pullback_models import (
    ExitReason,
    SimulationResult,
    TradeDirection,
    TradePlan,
    TradeResult,
)


@dataclass(frozen=True, slots=True)
class CostStress:
    spread_multiplier: float = 1.0
    additional_r_cost: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.spread_multiplier) or self.spread_multiplier < 1.0:
            raise ValueError("spread multiplier must be finite and at least one")
        if not math.isfinite(self.additional_r_cost) or self.additional_r_cost < 0:
            raise ValueError("additional R cost must be finite and nonnegative")


def _validate_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    columns: tuple[str, ...],
) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError(f"{name} must have a timezone-aware DatetimeIndex")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError(f"{name} must be sorted and unique")
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} missing columns: {', '.join(missing)}")
    result = frame.loc[:, columns].astype(float).copy()
    result.index = result.index.tz_convert("UTC")
    return result


def _stressed_ticks(ticks: pd.DataFrame, stress: CostStress) -> pd.DataFrame:
    result = ticks.copy()
    spread = (result["ask"] - result["bid"]) * stress.spread_multiplier
    if (spread < 0).any():
        raise ValueError("tick spread must be nonnegative")
    result["ask"] = result["bid"] + spread
    return result


def _abort_times(plan: TradePlan, bars: pd.DataFrame) -> tuple[pd.Timestamp, ...]:
    if bars.empty:
        return ()
    average = ema(bars["close"], 9)
    duration = pd.Timedelta(
        minutes=1 if plan.setup.candidate.abort_timeframe == "M1" else 5
    )
    times: list[pd.Timestamp] = []
    for position in range(1, len(bars)):
        previous_ema = average.iloc[position - 1]
        current_ema = average.iloc[position]
        if pd.isna(previous_ema) or pd.isna(current_ema):
            continue
        previous_close = float(bars["close"].iloc[position - 1])
        current_close = float(bars["close"].iloc[position])
        adverse_cross = (
            previous_close >= previous_ema and current_close < current_ema
            if plan.setup.direction is TradeDirection.LONG
            else previous_close <= previous_ema and current_close > current_ema
        )
        if adverse_cross:
            times.append(bars.index[position] + duration)
    return tuple(times)


def _close_trade(
    plan: TradePlan,
    *,
    entry_time: pd.Timestamp,
    entry_price: float,
    entry_spread: float,
    exit_time: pd.Timestamp,
    exit_price: float,
    reason: ExitReason,
    contract_size: float,
    stress: CostStress,
) -> SimulationResult:
    direction_sign = 1.0 if plan.setup.direction is TradeDirection.LONG else -1.0
    gross_cash = (
        (exit_price - entry_price)
        * direction_sign
        * plan.volume
        * contract_size
    )
    risk_cash = (
        abs(entry_price - plan.setup.stop) * plan.volume * contract_size
    )
    additional_cash = stress.additional_r_cost * risk_cash
    pnl_cash = gross_cash - additional_cash
    net_r = pnl_cash / risk_cash
    result = TradeResult(
        plan,
        entry_time,
        entry_price,
        exit_time,
        exit_price,
        reason,
        pnl_cash,
        net_r,
        entry_spread * plan.volume * contract_size,
        entry_time.tz_convert(ZoneInfo("America/New_York")).date(),
    )
    return SimulationResult(result, reason)


def simulate_trade(
    plan: TradePlan,
    ticks: pd.DataFrame,
    abort_bars: pd.DataFrame,
    session_end: pd.Timestamp,
    contract_size: float,
    stress: CostStress = CostStress(),
) -> SimulationResult:
    if session_end.tzinfo is None:
        raise ValueError("session_end must be timezone-aware")
    if not math.isfinite(contract_size) or contract_size <= 0:
        raise ValueError("contract_size must be finite and positive")
    quotes = _validate_frame(
        ticks,
        name="ticks",
        columns=("bid", "ask"),
    )
    bars = _validate_frame(
        abort_bars,
        name="abort bars",
        columns=("open", "high", "low", "close"),
    )
    quotes = _stressed_ticks(quotes, stress)
    end = session_end.tz_convert("UTC")
    cutoff = end - pd.Timedelta(minutes=15)
    quotes = quotes.loc[quotes.index < end]
    eligible = quotes.loc[quotes.index >= plan.setup.entry_available_time]
    if eligible.empty or eligible.index[0] > cutoff:
        return SimulationResult(None, ExitReason.ENTRY_TIMEOUT)

    first_time = eligible.index[0]
    first = eligible.iloc[0]
    first_spread = float(first["ask"] - first["bid"])
    spread_ceiling = min(
        plan.development_spread_ceiling,
        plan.setup.reference_spread * 2.0,
    )
    if first_spread > spread_ceiling:
        return SimulationResult(None, ExitReason.SPREAD_ABORT_BEFORE_ENTRY)
    entry_price = (
        float(first["ask"])
        if plan.setup.direction is TradeDirection.LONG
        else float(first["bid"])
    )
    abort_times = tuple(
        item
        for item in _abort_times(plan, bars)
        if item > first_time and item < end
    )

    for timestamp, row in eligible.iloc[1:].iterrows():
        executable = (
            float(row["bid"])
            if plan.setup.direction is TradeDirection.LONG
            else float(row["ask"])
        )
        stopped = (
            executable <= plan.setup.stop
            if plan.setup.direction is TradeDirection.LONG
            else executable >= plan.setup.stop
        )
        if stopped:
            return _close_trade(
                plan,
                entry_time=first_time,
                entry_price=entry_price,
                entry_spread=first_spread,
                exit_time=timestamp,
                exit_price=executable,
                reason=ExitReason.STOPPED,
                contract_size=contract_size,
                stress=stress,
            )
        targeted = (
            executable >= plan.target
            if plan.setup.direction is TradeDirection.LONG
            else executable <= plan.target
        )
        if targeted:
            return _close_trade(
                plan,
                entry_time=first_time,
                entry_price=entry_price,
                entry_spread=first_spread,
                exit_time=timestamp,
                exit_price=executable,
                reason=ExitReason.TARGET_CLOSED,
                contract_size=contract_size,
                stress=stress,
            )
        if any(item <= timestamp for item in abort_times):
            return _close_trade(
                plan,
                entry_time=first_time,
                entry_price=entry_price,
                entry_spread=first_spread,
                exit_time=timestamp,
                exit_price=executable,
                reason=ExitReason.MOMENTUM_ABORT,
                contract_size=contract_size,
                stress=stress,
            )

    final_time = eligible.index[-1]
    final_row = eligible.iloc[-1]
    final_price = (
        float(final_row["bid"])
        if plan.setup.direction is TradeDirection.LONG
        else float(final_row["ask"])
    )
    return _close_trade(
        plan,
        entry_time=first_time,
        entry_price=entry_price,
        entry_spread=first_spread,
        exit_time=final_time,
        exit_price=final_price,
        reason=ExitReason.SESSION_FLATTENED,
        contract_size=contract_size,
        stress=stress,
    )
