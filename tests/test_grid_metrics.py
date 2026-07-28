from dataclasses import replace

import pandas as pd
import pytest

from gscalp.grid_metrics import (
    GridMetrics,
    bootstrap_expectancy_lower_bound,
    development_gate,
    summarize_baskets,
    test_gate,
    validation_gate,
)
from gscalp.grid_models import BasketResult, BiasDirection, GridReason


START = pd.Timestamp("2024-01-01 08:00:00+00:00")


def basket(
    number: int,
    net_r: float,
    *,
    year: int = 2024,
    reason: GridReason = GridReason.TARGET_CLOSED,
    maximum_levels_filled: int = 1,
    mfe_r: float = 0.60,
    mae_r: float = -0.20,
) -> BasketResult:
    session_start = START.replace(year=year) + pd.Timedelta(days=number)
    return BasketResult(
        basket_id=f"basket-{number}",
        direction=BiasDirection.LONG,
        session_start=session_start,
        exit_time=session_start + pd.Timedelta(minutes=30),
        reason=reason,
        legs=(),
        gross_r=net_r + 0.05,
        cost_r=0.05,
        net_r=net_r,
        mfe_r=mfe_r,
        mae_r=mae_r,
        maximum_levels_filled=maximum_levels_filled,
    )


def metrics(**changes: float | int) -> GridMetrics:
    baseline = GridMetrics(
        basket_count=100,
        win_rate=0.60,
        expectancy_r=0.10,
        profit_factor=1.20,
        max_drawdown_r=5.0,
        max_consecutive_losses=3,
        average_mfe_r=0.60,
        average_mae_r=-0.20,
        forced_close_rate=0.10,
        average_levels_filled=1.50,
        maximum_year_share=0.30,
        worst_basket_r=-1.00,
    )
    return replace(baseline, **changes)


def test_summarize_baskets_calculates_chronological_returns_and_drawdown():
    result = summarize_baskets(
        [basket(1, 0.40), basket(2, 0.40), basket(3, -1.00), basket(4, 0.40)]
    )

    assert result.basket_count == 4
    assert result.win_rate == pytest.approx(0.75)
    assert result.expectancy_r == pytest.approx(0.05)
    assert result.profit_factor == pytest.approx(1.2)
    assert result.max_drawdown_r == pytest.approx(1.0)
    assert result.max_consecutive_losses == 1
    assert result.worst_basket_r == pytest.approx(-1.0)


def test_summarize_baskets_reports_fill_close_and_year_distribution_metrics():
    result = summarize_baskets(
        [
            basket(1, 0.40, year=2023, maximum_levels_filled=1, mfe_r=0.40, mae_r=-0.10),
            basket(2, -0.20, year=2024, reason=GridReason.SESSION_FLATTENED, maximum_levels_filled=2, mfe_r=0.60, mae_r=-0.30),
            basket(3, 0.30, year=2024, maximum_levels_filled=3, mfe_r=0.80, mae_r=-0.20),
        ]
    )

    assert result.average_mfe_r == pytest.approx(0.60)
    assert result.average_mae_r == pytest.approx(-0.20)
    assert result.forced_close_rate == pytest.approx(1 / 3)
    assert result.average_levels_filled == pytest.approx(2.0)
    assert result.maximum_year_share == pytest.approx(2 / 3)


def test_bootstrap_is_deterministic_for_fixed_seed():
    a = bootstrap_expectancy_lower_bound(
        [0.4, 0.4, -1.0, 0.4] * 30, confidence=0.90, samples=5_000, seed=260728
    )
    b = bootstrap_expectancy_lower_bound(
        [0.4, 0.4, -1.0, 0.4] * 30, confidence=0.90, samples=5_000, seed=260728
    )
    assert a == b


@pytest.mark.parametrize(
    ("gate", "minimum"),
    [(development_gate, 100), (validation_gate, 30)],
)
def test_research_gates_reject_insufficient_baskets(gate, minimum):
    assert not gate(metrics(basket_count=minimum - 1), metrics())


@pytest.mark.parametrize(
    "base_changes, stressed_changes",
    [
        ({"expectancy_r": 0.0}, {}),
        ({"profit_factor": 1.15}, {}),
        ({"max_drawdown_r": 8.01}, {}),
        ({"maximum_year_share": 0.351}, {}),
        ({}, {"expectancy_r": 0.0}),
        ({}, {"worst_basket_r": -1.11}),
    ],
)
def test_development_gate_rejects_each_performance_limit(base_changes, stressed_changes):
    assert not development_gate(metrics(**base_changes), metrics(**stressed_changes))


@pytest.mark.parametrize(
    "base_changes, stressed_changes",
    [
        ({"expectancy_r": 0.0}, {}),
        ({"profit_factor": 1.15}, {}),
        ({"max_drawdown_r": 8.01}, {}),
        ({"maximum_year_share": 0.351}, {}),
        ({}, {"expectancy_r": 0.0}),
        ({}, {"worst_basket_r": -1.11}),
    ],
)
def test_validation_gate_rejects_each_performance_limit(base_changes, stressed_changes):
    assert not validation_gate(metrics(basket_count=30, **base_changes), metrics(**stressed_changes))


def test_test_gate_rejects_insufficient_baskets():
    assert not test_gate(metrics(basket_count=19), metrics(), bootstrap_lower=0.00)


@pytest.mark.parametrize(
    "base_changes, stressed_changes, bootstrap_lower",
    [
        ({"expectancy_r": 0.0}, {}, 0.00),
        ({"profit_factor": 1.10}, {}, 0.00),
        ({"max_drawdown_r": 8.01}, {}, 0.00),
        ({}, {"expectancy_r": 0.0}, 0.00),
        ({}, {}, -0.051),
    ],
)
def test_test_gate_rejects_each_applicable_performance_limit(
    base_changes, stressed_changes, bootstrap_lower
):
    assert not test_gate(
        metrics(basket_count=20, **base_changes),
        metrics(**stressed_changes),
        bootstrap_lower=bootstrap_lower,
    )
