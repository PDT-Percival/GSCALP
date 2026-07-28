from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import pandas as pd

from .models import Direction, SignalDecision


class ExitReason(str, Enum):
    TARGET = "target"
    STOP = "stop"
    SESSION_END = "session_end"


@dataclass(frozen=True, slots=True)
class TradeResult:
    direction: Direction
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop: float
    target: float
    exit_reason: ExitReason
    gross_r: float
    cost_r: float
    net_r: float
    mfe_r: float
    mae_r: float


def _validate_ticks(ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks.index.tz is None:
        raise ValueError("tick index must be timezone-aware")
    if not {"bid", "ask"}.issubset(ticks.columns):
        raise ValueError("ticks must contain bid and ask columns")
    if not ticks.index.is_monotonic_increasing:
        raise ValueError("ticks must be ordered by time")
    return ticks


def simulate_trade(
    decision: SignalDecision,
    ticks: pd.DataFrame,
    session_end: pd.Timestamp,
    *,
    signal_bar_minutes: int = 5,
    not_before: pd.Timestamp | None = None,
    cost_r: float = 0.0,
) -> TradeResult | None:
    if not decision.eligible or decision.direction is None:
        return None
    if decision.signal_time is None or decision.stop is None or decision.target is None:
        raise ValueError("qualified signal is missing execution prices")
    market = _validate_ticks(ticks)
    entry_start = decision.signal_time + pd.Timedelta(minutes=signal_bar_minutes)
    if not_before is not None:
        entry_start = max(entry_start, not_before)
    available = market.loc[(market.index >= entry_start) & (market.index < session_end)]
    if available.empty:
        return None

    entry_time = available.index[0]
    if decision.direction is Direction.LONG:
        entry_price = float(available.iloc[0]["ask"])
    else:
        entry_price = float(available.iloc[0]["bid"])
    risk = abs(entry_price - decision.stop)
    if risk <= 0:
        raise ValueError("actual entry produces nonpositive risk")

    exit_time = available.index[-1]
    exit_reason = ExitReason.SESSION_END
    exit_price = float(
        available.iloc[-1]["bid"]
        if decision.direction is Direction.LONG
        else available.iloc[-1]["ask"]
    )
    path_prices: list[float] = []
    for timestamp, tick in available.iterrows():
        executable = float(
            tick["bid"] if decision.direction is Direction.LONG else tick["ask"]
        )
        path_prices.append(executable)
        if decision.direction is Direction.LONG:
            if executable <= decision.stop:
                exit_time, exit_price, exit_reason = timestamp, executable, ExitReason.STOP
                break
            if executable >= decision.target:
                exit_time, exit_price, exit_reason = timestamp, executable, ExitReason.TARGET
                break
        else:
            if executable >= decision.stop:
                exit_time, exit_price, exit_reason = timestamp, executable, ExitReason.STOP
                break
            if executable <= decision.target:
                exit_time, exit_price, exit_reason = timestamp, executable, ExitReason.TARGET
                break

    path = pd.Series(path_prices, dtype=float)
    if decision.direction is Direction.LONG:
        excursions = (path - entry_price) / risk
        gross_r = (exit_price - entry_price) / risk
    else:
        excursions = (entry_price - path) / risk
        gross_r = (entry_price - exit_price) / risk
    return TradeResult(
        direction=decision.direction,
        signal_time=decision.signal_time,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=entry_price,
        exit_price=exit_price,
        stop=float(decision.stop),
        target=float(decision.target),
        exit_reason=exit_reason,
        gross_r=float(gross_r),
        cost_r=float(cost_r),
        net_r=float(gross_r - cost_r),
        mfe_r=float(excursions.max()),
        mae_r=float(excursions.min()),
    )


def run_signal_backtest(
    signals: Iterable[SignalDecision],
    ticks: pd.DataFrame,
    *,
    session_end: pd.Timestamp,
    max_trades: int,
    daily_loss_limit_r: float,
) -> list[TradeResult]:
    if max_trades < 1:
        raise ValueError("max_trades must be positive")
    trades: list[TradeResult] = []
    cumulative_r = 0.0
    not_before: pd.Timestamp | None = None
    eligible = sorted(
        (item for item in signals if item.eligible and item.signal_time is not None),
        key=lambda item: item.signal_time,
    )
    for item in eligible:
        if len(trades) >= max_trades or cumulative_r <= -daily_loss_limit_r:
            break
        trade = simulate_trade(
            item,
            ticks,
            session_end,
            not_before=not_before,
        )
        if trade is None:
            continue
        trades.append(trade)
        cumulative_r += trade.net_r
        not_before = trade.exit_time + pd.Timedelta(microseconds=1)
    return trades

