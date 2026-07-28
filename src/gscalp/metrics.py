from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .backtest import TradeResult


@dataclass(frozen=True, slots=True)
class MetricsReport:
    trade_count: int
    win_rate: float
    gross_expectancy_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    max_consecutive_losses: int
    average_mfe_r: float
    average_mae_r: float
    total_cost_r: float


def summarize(trades: Iterable[TradeResult]) -> MetricsReport:
    items = list(trades)
    if not items:
        return MetricsReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
    net = np.array([item.net_r for item in items], dtype=float)
    gross = np.array([item.gross_r for item in items], dtype=float)
    wins = net[net > 0]
    losses = net[net < 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf")
    equity = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = np.maximum.accumulate(equity) - equity
    consecutive = 0
    maximum_consecutive = 0
    for value in net:
        if value < 0:
            consecutive += 1
            maximum_consecutive = max(maximum_consecutive, consecutive)
        else:
            consecutive = 0
    return MetricsReport(
        trade_count=len(items),
        win_rate=float(np.mean(net > 0)),
        gross_expectancy_r=float(gross.mean()),
        expectancy_r=float(net.mean()),
        profit_factor=profit_factor,
        max_drawdown_r=float(drawdown.max()),
        max_consecutive_losses=maximum_consecutive,
        average_mfe_r=float(np.mean([item.mfe_r for item in items])),
        average_mae_r=float(np.mean([item.mae_r for item in items])),
        total_cost_r=float(sum(item.cost_r for item in items)),
    )


def chronological_split(
    frame: pd.DataFrame,
    development_fraction: float,
    validation_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0 < development_fraction < 1:
        raise ValueError("development_fraction must be between zero and one")
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between zero and one")
    if development_fraction + validation_fraction >= 1:
        raise ValueError("development and validation fractions must leave a test tail")
    ordered = frame.sort_index()
    development_end = int(len(ordered) * development_fraction)
    validation_end = development_end + int(len(ordered) * validation_fraction)
    return (
        ordered.iloc[:development_end].copy(),
        ordered.iloc[development_end:validation_end].copy(),
        ordered.iloc[validation_end:].copy(),
    )
