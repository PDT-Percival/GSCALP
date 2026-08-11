from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from gscalp.pullback_config import PullbackCandidate
from gscalp.pullback_metrics import (
    PullbackMetrics,
    bootstrap_expectancy_lower_bound,
    development_gate,
    summarize_trades,
    test_gate as historical_test_gate,
    validation_gate,
    validation_score,
)
from gscalp.pullback_models import (
    ExitReason,
    PullbackSetup,
    TradeDirection,
    TradePlan,
    TradeResult,
)


def trade(net_r, local_date, sequence):
    timestamp = pd.Timestamp(local_date, tz="UTC") + pd.Timedelta(minutes=sequence)
    setup = PullbackSetup(
        PullbackCandidate("09:30-10:30", "M1", 0.50, "M1"),
        TradeDirection.LONG,
        2.0,
        99.4,
        101.0,
        timestamp,
        timestamp,
        100.0,
        99.0,
        0.20,
    )
    plan = TradePlan(
        f"trade-{sequence}", setup, 100.0, 100.5, 0.10, 0.30,
        15.0, 50.0, 10_000.0,
    )
    return TradeResult(
        plan,
        timestamp,
        100.0,
        timestamp + pd.Timedelta(minutes=1),
        100.0 + net_r,
        ExitReason.TARGET_CLOSED if net_r > 0 else ExitReason.STOPPED,
        net_r * 10.0,
        net_r,
        2.0,
        date.fromisoformat(local_date),
    )


def test_summary_calculates_returns_drawdown_and_year_concentration():
    trades = [
        trade(-1.0, "2023-01-02", 1),
        trade(2.0, "2023-02-02", 2),
        trade(-0.5, "2024-01-02", 3),
        trade(1.5, "2025-01-02", 4),
    ]

    metrics = summarize_trades(reversed(trades))

    assert metrics.trade_count == 4
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.expectancy_r == pytest.approx(0.5)
    assert metrics.standard_deviation_r == pytest.approx(1.4719601443879744)
    assert metrics.standard_error_r == pytest.approx(0.7359800721939872)
    assert metrics.profit_factor == pytest.approx(3.5 / 1.5)
    assert metrics.max_drawdown_r == pytest.approx(1.0)
    assert metrics.minimum_trade_r == pytest.approx(-1.0)
    assert metrics.maximum_year_share == pytest.approx(0.5)


def test_profit_factor_handles_no_losses_and_no_wins():
    all_wins = summarize_trades([trade(0.5, "2024-01-02", 1)])
    all_losses = summarize_trades([trade(-0.5, "2024-01-02", 1)])

    assert all_wins.profit_factor == float("inf")
    assert all_losses.profit_factor == 0.0


def test_bootstrap_is_deterministic_with_literal_expected_quantile():
    values = [-1.0, 2.0, -0.5, 1.5]

    first = bootstrap_expectancy_lower_bound(values)
    second = bootstrap_expectancy_lower_bound(values)

    assert first == pytest.approx(-0.25)
    assert second == first
    assert bootstrap_expectancy_lower_bound([]) == float("-inf")


def passing_metrics(count):
    return PullbackMetrics(
        trade_count=count,
        win_rate=0.55,
        expectancy_r=0.10,
        standard_deviation_r=0.50,
        standard_error_r=0.05,
        profit_factor=1.20,
        max_drawdown_r=8.0,
        minimum_trade_r=-1.10,
        maximum_year_share=0.35,
    )


@pytest.mark.parametrize(
    ("target", "changes"),
    [
        ("base", {"trade_count": 99}),
        ("base", {"expectancy_r": 0.0}),
        ("base", {"profit_factor": 1.15}),
        ("base", {"max_drawdown_r": 8.01}),
        ("base", {"maximum_year_share": 0.351}),
        ("spread", {"expectancy_r": 0.0}),
        ("spread", {"minimum_trade_r": -1.101}),
        ("cost", {"expectancy_r": 0.0}),
        ("cost", {"minimum_trade_r": -1.101}),
    ],
)
def test_development_gate_rejects_every_performance_boundary(target, changes):
    base = passing_metrics(100)
    spread = passing_metrics(100)
    cost = passing_metrics(100)
    values = {"base": base, "spread": spread, "cost": cost}
    values[target] = replace(values[target], **changes)

    assert not development_gate(values["base"], values["spread"], values["cost"], -0.05)


def test_development_gate_accepts_exact_inclusive_risk_bounds():
    metrics = passing_metrics(100)

    assert development_gate(metrics, metrics, metrics, -0.05)
    assert not development_gate(metrics, metrics, metrics, -0.051)


@pytest.mark.parametrize(
    ("target", "changes"),
    [
        ("base", {"trade_count": 29}),
        ("base", {"expectancy_r": 0.0}),
        ("base", {"profit_factor": 1.10}),
        ("base", {"max_drawdown_r": 8.01}),
        ("spread", {"expectancy_r": 0.0}),
        ("spread", {"minimum_trade_r": -1.101}),
    ],
)
def test_validation_gate_rejects_every_performance_boundary(target, changes):
    base = passing_metrics(30)
    spread = passing_metrics(30)
    values = {"base": base, "spread": spread}
    values[target] = replace(values[target], **changes)

    assert not validation_gate(values["base"], values["spread"])


def test_validation_gate_accepts_passing_metrics():
    metrics = passing_metrics(30)
    assert validation_gate(metrics, metrics)


@pytest.mark.parametrize(
    ("target", "changes"),
    [
        ("base", {"trade_count": 19}),
        ("base", {"expectancy_r": 0.0}),
        ("base", {"profit_factor": 1.10}),
        ("base", {"max_drawdown_r": 8.01}),
        ("spread", {"expectancy_r": 0.0}),
    ],
)
def test_test_gate_rejects_every_performance_boundary(target, changes):
    base = passing_metrics(20)
    spread = passing_metrics(20)
    values = {"base": base, "spread": spread}
    values[target] = replace(values[target], **changes)

    assert not historical_test_gate(values["base"], values["spread"], -0.05)


def test_test_gate_accepts_bootstrap_boundary_and_rejects_below_it():
    metrics = passing_metrics(20)

    assert historical_test_gate(metrics, metrics, -0.05)
    assert not historical_test_gate(metrics, metrics, -0.051)


def test_validation_score_penalizes_standard_error():
    metrics = replace(
        passing_metrics(30), expectancy_r=0.20, standard_error_r=0.07
    )

    assert validation_score(metrics) == pytest.approx(0.13)

