from pathlib import Path

import pandas as pd
import pytest

from gscalp.grid_bias import confirmed_pivot, evaluate_locked_bias
from gscalp.grid_config import GridConfig, load_grid_config
from gscalp.grid_models import BiasDirection, GridReason

@pytest.fixture
def grid_config() -> GridConfig:
    return load_grid_config(Path(__file__).parents[1] / "config" / "grid-v1.0.json")


@pytest.fixture
def bullish_m15() -> pd.DataFrame:
    index = pd.date_range("2026-07-15 08:00", periods=30, freq="15min", tz="UTC")
    close = pd.Series([90 + number * 0.4 for number in range(30)], index=index)
    return pd.DataFrame(
        {"open": close - 0.1, "high": close + 0.3, "low": close - 0.3, "close": close},
        index=index,
    )


@pytest.fixture
def pivot_m5() -> pd.DataFrame:
    index = pd.date_range("2026-07-15 08:00", periods=8, freq="5min", tz="UTC")
    lows = [100.0, 99.9, 99.8, 99.7, 99.8, 99.6, 99.8, 99.9]
    return pd.DataFrame(
        {
            "open": [100.5] * len(index),
            "high": [101.0] * len(index),
            "low": lows,
            "close": [100.5] * len(index),
        },
        index=index,
    )


def test_bullish_bias_uses_only_completed_m15_bars(grid_config, bullish_m15):
    as_of = bullish_m15.index[-1] + pd.Timedelta(minutes=15)
    expected = evaluate_locked_bias(bullish_m15, as_of, grid_config)
    future = bullish_m15.copy()
    future.loc[as_of] = {"open": 1, "high": 10_000, "low": 0, "close": 1}
    actual = evaluate_locked_bias(future, as_of, grid_config)
    assert expected == actual
    assert actual.direction is BiasDirection.LONG
    assert actual.reason is GridReason.BIAS_LOCKED


def test_neutral_bias_when_structure_disagrees(grid_config, bullish_m15):
    broken = bullish_m15.copy()
    broken.iloc[-1, broken.columns.get_loc("low")] = broken.iloc[-2]["low"] - 1
    result = evaluate_locked_bias(
        broken, broken.index[-1] + pd.Timedelta(minutes=15), grid_config
    )
    assert result.direction is None
    assert result.reason is GridReason.NEUTRAL_BIAS


def test_pivot_requires_two_completed_bars_on_the_right(grid_config, pivot_m5):
    as_of = pivot_m5.index[-1] + pd.Timedelta(minutes=5)
    pivot = confirmed_pivot(pivot_m5, as_of, BiasDirection.LONG, grid_config)
    assert pivot == (pivot_m5.index[-3], pivot_m5.iloc[-3]["low"])
    changed_future = pivot_m5.copy()
    changed_future.loc[as_of] = {"open": 0, "high": 1, "low": -999, "close": 0}
    assert confirmed_pivot(
        changed_future, as_of, BiasDirection.LONG, grid_config
    ) == pivot
