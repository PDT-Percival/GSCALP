from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .pullback_models import TradeResult


DEVELOPMENT_MIN_TRADES = 100
VALIDATION_MIN_TRADES = 30
TEST_MIN_TRADES = 20
DEVELOPMENT_MIN_PROFIT_FACTOR = 1.15
LATER_MIN_PROFIT_FACTOR = 1.10
MAX_DRAWDOWN_R = 8.0
MAX_YEAR_SHARE = 0.35
MIN_STRESSED_TRADE_R = -1.10
MIN_BOOTSTRAP_EXPECTANCY_R = -0.05


@dataclass(frozen=True, slots=True)
class PullbackMetrics:
    trade_count: int
    win_rate: float
    expectancy_r: float
    standard_deviation_r: float
    standard_error_r: float
    profit_factor: float
    max_drawdown_r: float
    minimum_trade_r: float
    maximum_year_share: float


def summarize_trades(trades: Iterable[TradeResult]) -> PullbackMetrics:
    ordered = sorted(trades, key=lambda trade: trade.entry_time)
    if not ordered:
        return PullbackMetrics(
            0,
            0.0,
            float("-inf"),
            float("inf"),
            float("inf"),
            0.0,
            0.0,
            float("-inf"),
            1.0,
        )
    returns = np.asarray([trade.net_r for trade in ordered], dtype=float)
    count = len(returns)
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    gross_profit = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
        if gross_profit > 0
        else 0.0
    )
    deviation = float(np.std(returns, ddof=1)) if count > 1 else 0.0
    cumulative = np.cumsum(returns)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))
    drawdowns = peaks[1:] - cumulative
    years: dict[int, int] = {}
    for trade in ordered:
        years[trade.local_date.year] = years.get(trade.local_date.year, 0) + 1
    return PullbackMetrics(
        trade_count=count,
        win_rate=float(np.count_nonzero(returns > 0) / count),
        expectancy_r=float(np.mean(returns)),
        standard_deviation_r=deviation,
        standard_error_r=deviation / math.sqrt(count),
        profit_factor=profit_factor,
        max_drawdown_r=float(drawdowns.max(initial=0.0)),
        minimum_trade_r=float(returns.min()),
        maximum_year_share=max(years.values()) / count,
    )


def bootstrap_expectancy_lower_bound(
    net_r: Sequence[float],
    *,
    seed: int = 1101,
    samples: int = 10_000,
    confidence: float = 0.90,
) -> float:
    values = np.asarray(net_r, dtype=float)
    if values.size == 0:
        return float("-inf")
    if samples <= 0 or not 0 < confidence < 1:
        raise ValueError("bootstrap settings are invalid")
    generator = np.random.default_rng(seed)
    resampled_means = generator.choice(
        values,
        size=(samples, values.size),
        replace=True,
    ).mean(axis=1)
    return float(np.quantile(resampled_means, 1.0 - confidence))


def development_gate(
    base: PullbackMetrics,
    spread_stress: PullbackMetrics,
    cost_stress: PullbackMetrics,
    bootstrap_lower: float,
) -> bool:
    return (
        base.trade_count >= DEVELOPMENT_MIN_TRADES
        and base.expectancy_r > 0
        and base.profit_factor > DEVELOPMENT_MIN_PROFIT_FACTOR
        and spread_stress.expectancy_r > 0
        and cost_stress.expectancy_r > 0
        and base.max_drawdown_r <= MAX_DRAWDOWN_R
        and base.maximum_year_share <= MAX_YEAR_SHARE
        and spread_stress.minimum_trade_r >= MIN_STRESSED_TRADE_R
        and cost_stress.minimum_trade_r >= MIN_STRESSED_TRADE_R
        and bootstrap_lower >= MIN_BOOTSTRAP_EXPECTANCY_R
    )


def validation_gate(
    base: PullbackMetrics,
    spread_stress: PullbackMetrics,
) -> bool:
    return (
        base.trade_count >= VALIDATION_MIN_TRADES
        and base.expectancy_r > 0
        and base.profit_factor > LATER_MIN_PROFIT_FACTOR
        and spread_stress.expectancy_r > 0
        and base.max_drawdown_r <= MAX_DRAWDOWN_R
        and spread_stress.minimum_trade_r >= MIN_STRESSED_TRADE_R
    )


def test_gate(
    base: PullbackMetrics,
    spread_stress: PullbackMetrics,
    bootstrap_lower: float,
) -> bool:
    return (
        base.trade_count >= TEST_MIN_TRADES
        and base.expectancy_r > 0
        and base.profit_factor > LATER_MIN_PROFIT_FACTOR
        and spread_stress.expectancy_r > 0
        and base.max_drawdown_r <= MAX_DRAWDOWN_R
        and bootstrap_lower >= MIN_BOOTSTRAP_EXPECTANCY_R
    )


def validation_score(metrics: PullbackMetrics) -> float:
    return metrics.expectancy_r - metrics.standard_error_r
