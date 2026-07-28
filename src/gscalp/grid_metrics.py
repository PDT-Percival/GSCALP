from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .grid_models import BasketResult, GridReason


@dataclass(frozen=True, slots=True)
class GridMetrics:
    basket_count: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    max_consecutive_losses: int
    average_mfe_r: float
    average_mae_r: float
    forced_close_rate: float
    average_levels_filled: float
    maximum_year_share: float
    worst_basket_r: float


def maximum_consecutive_losses(net_r: Sequence[float] | np.ndarray) -> int:
    longest = 0
    current = 0
    for value in net_r:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def summarize_baskets(baskets: Iterable[BasketResult]) -> GridMetrics:
    items = list(baskets)
    net = np.asarray([item.net_r for item in items], dtype=float)
    wins, losses = net[net > 0], net[net < 0]
    equity = np.concatenate(([0.0], np.cumsum(net)))
    drawdown = np.maximum.accumulate(equity) - equity
    years = pd.Series([item.session_start.year for item in items]).value_counts()
    return GridMetrics(
        basket_count=len(items),
        win_rate=float(np.mean(net > 0)) if len(net) else 0.0,
        expectancy_r=float(net.mean()) if len(net) else 0.0,
        profit_factor=float(wins.sum() / abs(losses.sum())) if len(losses) else float("inf"),
        max_drawdown_r=float(drawdown.max()) if len(drawdown) else 0.0,
        max_consecutive_losses=maximum_consecutive_losses(net),
        average_mfe_r=float(np.mean([item.mfe_r for item in items])) if items else 0.0,
        average_mae_r=float(np.mean([item.mae_r for item in items])) if items else 0.0,
        forced_close_rate=float(
            np.mean([item.reason is GridReason.SESSION_FLATTENED for item in items])
        ) if items else 0.0,
        average_levels_filled=float(
            np.mean([item.maximum_levels_filled for item in items])
        ) if items else 0.0,
        maximum_year_share=float(years.max() / len(items)) if items else 1.0,
        worst_basket_r=float(net.min()) if len(net) else 0.0,
    )


def bootstrap_expectancy_lower_bound(
    values: Iterable[float], confidence: float, samples: int, seed: int
) -> float:
    observed = np.asarray(list(values), dtype=float)
    if len(observed) == 0:
        return 0.0
    generator = np.random.default_rng(seed)
    resampled_means = generator.choice(
        observed, size=(samples, len(observed)), replace=True
    ).mean(axis=1)
    return float(np.quantile(resampled_means, 1.0 - confidence))


def development_gate(base: GridMetrics, stressed: GridMetrics) -> bool:
    return (
        base.basket_count >= 100
        and base.expectancy_r > 0
        and base.profit_factor > 1.15
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and base.maximum_year_share <= 0.35
        and stressed.worst_basket_r >= -1.10
    )


def validation_gate(base: GridMetrics, stressed: GridMetrics) -> bool:
    return (
        base.basket_count >= 30
        and base.expectancy_r > 0
        and base.profit_factor > 1.15
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and base.maximum_year_share <= 0.35
        and stressed.worst_basket_r >= -1.10
    )


def test_gate(base: GridMetrics, stressed: GridMetrics, bootstrap_lower: float) -> bool:
    return (
        base.basket_count >= 20
        and base.expectancy_r > 0
        and base.profit_factor > 1.10
        and stressed.expectancy_r > 0
        and base.max_drawdown_r <= 8.0
        and bootstrap_lower >= -0.05
    )


test_gate.__test__ = False
